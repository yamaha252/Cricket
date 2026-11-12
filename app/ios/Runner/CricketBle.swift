import AVFoundation
import CoreBluetooth
import Flutter
import UIKit

/// Own BLE layer for Cricket on iOS, the CoreBluetooth twin of
/// android/.../CricketBle.kt: same channels, methods and event maps.
///
/// iOS differences the Dart side has to live with:
/// - iPhone does not receive Coded PHY (docs/app.md): only 1M packets arrive,
///   every packet is reported with primaryPhy 1.
/// - There is no MAC address: "address" is the CBPeripheral identifier (UUID),
///   stable on this phone only.
/// - There is no createBond: iOS pairs when a protected characteristic answers
///   "insufficient encryption". createBond reads the settings characteristic
///   (READ_ENCRYPT in the firmware) on the open link and reports the outcome as
///   a "bond" event. bondState is unknown to apps, it is always "none", so the
///   app always goes through that read, which is harmless when already bonded.
final class CricketBle: NSObject, CBCentralManagerDelegate, CBPeripheralDelegate, FlutterStreamHandler {
  static let companyId: UInt16 = 0xFFFF
  static let protocolVersion: UInt8 = 2
  static let settingsUuid = CBUUID(string: "2083eb8d-7651-438b-b7fb-75aff5da9c03")

  private var central: CBCentralManager?
  private var scanSink: FlutterEventSink?
  private var connSink: FlutterEventSink?
  private var wantScan = false
  private var filtered = true
  private var permissionWaiters: [FlutterResult] = []
  private var adapterWaiters: [FlutterResult] = []

  private func flushAdapterWaiters() {
    guard !adapterWaiters.isEmpty else { return }
    let info = adapterInfo()
    adapterWaiters.forEach { $0(info) }
    adapterWaiters.removeAll()
  }

  /// Peripherals seen while scanning, by identifier: connect() needs the object.
  private var seen: [UUID: CBPeripheral] = [:]
  private var peripheral: CBPeripheral?
  private var pending: FlutterResult?
  private var pendingKind = ""
  /// Characteristic the pending operation is for: an answer for another one
  /// (a notification) must not complete it.
  private var pendingUuid: CBUUID?
  private var bonding = false
  /// connect() arrived while the same peripheral was still disconnecting:
  /// connect again once didDisconnect comes, instead of reporting that
  /// disconnect to the new attempt.
  private var reconnect = false

  private let audio = AVAudioEngine()
  private let player = AVAudioPlayerNode()
  private var audioReady = false
  private var audioIdle: DispatchWorkItem?

  init(messenger: FlutterBinaryMessenger) {
    super.init()
    FlutterMethodChannel(name: "cricket/ble", binaryMessenger: messenger).setMethodCallHandler { [weak self] call, result in
      self?.handle(call, result)
    }
    FlutterEventChannel(name: "cricket/scan", binaryMessenger: messenger).setStreamHandler(ScanHandler(owner: self))
    FlutterEventChannel(name: "cricket/conn", binaryMessenger: messenger).setStreamHandler(self)
  }

  // Event channel handlers: self handles "conn", ScanHandler handles "scan".
  func onListen(withArguments arguments: Any?, eventSink events: @escaping FlutterEventSink) -> FlutterError? {
    connSink = events
    return nil
  }

  func onCancel(withArguments arguments: Any?) -> FlutterError? {
    connSink = nil
    return nil
  }

  private final class ScanHandler: NSObject, FlutterStreamHandler {
    weak var owner: CricketBle?
    init(owner: CricketBle) { self.owner = owner }
    func onListen(withArguments arguments: Any?, eventSink events: @escaping FlutterEventSink) -> FlutterError? {
      owner?.scanSink = events
      return nil
    }
    func onCancel(withArguments arguments: Any?) -> FlutterError? {
      owner?.scanSink = nil
      return nil
    }
  }

  /// Creating the manager is what shows the Bluetooth permission prompt, so
  /// it is created lazily, on the first call that needs Bluetooth.
  private func manager() -> CBCentralManager {
    if let c = central { return c }
    let c = CBCentralManager(delegate: self, queue: nil, options: [CBCentralManagerOptionShowPowerAlertKey: false])
    central = c
    return c
  }

  private var authorized: Bool { CBManager.authorization == .allowedAlways }

  // MARK: - Method channel

  private func handle(_ call: FlutterMethodCall, _ result: @escaping FlutterResult) {
    let args = call.arguments as? [String: Any] ?? [:]
    switch call.method {
    case "adapterInfo":
      // Right after creation the manager says "unknown" for a moment: answer
      // after the first real state, or the app would show "Bluetooth off".
      let st = central?.state
      if authorized && (st == nil || st == .unknown || st == .resetting) {
        adapterWaiters.append(result)
        _ = manager()
        DispatchQueue.main.asyncAfter(deadline: .now() + 3) { [weak self] in self?.flushAdapterWaiters() }
      } else {
        result(adapterInfo())
      }
    case "hasPermissions":
      result(authorized)
    case "requestPermissions":
      switch CBManager.authorization {
      case .allowedAlways: result(true)
      case .denied, .restricted: result(false)
      default:
        // notDetermined: the prompt appears when the manager is created, the
        // answer arrives as a state update.
        permissionWaiters.append(result)
        _ = manager()
      }
    case "openAppSettings", "requestEnable":
      // iOS has no "turn Bluetooth on" dialog for apps: the app's settings page
      // is the closest place (Bluetooth permission and a link to Bluetooth).
      if let url = URL(string: UIApplication.openSettingsURLString) {
        UIApplication.shared.open(url)
      }
      result(nil)
    case "startScan":
      result(startScan(filtered: args["filtered"] as? Bool ?? true))
    case "stopScan":
      stopScan()
      result(nil)
    case "connect":
      connect(args["address"] as? String ?? "", result)
    case "disconnect":
      reconnect = false
      if let p = peripheral { central?.cancelPeripheralConnection(p) }
      result(nil)
    case "read":
      read(args["uuid"] as? String ?? "", result)
    case "write":
      let value = (args["value"] as? FlutterStandardTypedData)?.data ?? Data()
      write(args["uuid"] as? String ?? "", value, result)
    case "notify":
      setNotify(args["uuid"] as? String ?? "", result)
    case "createBond":
      createBond(args["address"] as? String ?? "", result)
    case "bondState":
      result("none")
    case "keepScreenOn":
      UIApplication.shared.isIdleTimerDisabled = args["on"] as? Bool ?? false
      result(nil)
    case "beep":
      beep(ms: args["ms"] as? Int ?? 60)
      result(nil)
    default:
      result(FlutterMethodNotImplemented)
    }
  }

  private func adapterInfo() -> [String: Any?] {
    var name = "iPhone"
    var info = utsname()
    if uname(&info) == 0 {
      name = withUnsafePointer(to: &info.machine) {
        $0.withMemoryRebound(to: CChar.self, capacity: 1) { String(cString: $0) }
      }
    }
    // Only ask the manager for its state when permission was already given,
    // otherwise this call would show the prompt.
    let state: CBManagerState = authorized ? manager().state : .unknown
    return [
      "present": state != .unsupported,
      "enabled": state == .poweredOn,
      "codedSupported": false,
      "extendedSupported": CBCentralManager.supports(.extendedScanAndConnect),
      "sdk": 0,
      "model": name,
      "platform": "ios",
    ]
  }

  // MARK: - Scanning

  private func startScan(filtered: Bool) -> Bool {
    self.filtered = filtered
    wantScan = true
    let c = manager()
    guard c.state == .poweredOn else { return c.state != .unsupported && authorized }
    c.scanForPeripherals(withServices: nil, options: [CBCentralManagerScanOptionAllowDuplicatesKey: true])
    return true
  }

  private func stopScan() {
    wantScan = false
    if central?.isScanning == true { central?.stopScan() }
  }

  func centralManager(_ central: CBCentralManager, didDiscover p: CBPeripheral,
                      advertisementData ad: [String: Any], rssi RSSI: NSNumber) {
    guard let mfr = ad[CBAdvertisementDataManufacturerDataKey] as? Data, mfr.count >= 3 else { return }
    let company = UInt16(mfr[mfr.startIndex]) | UInt16(mfr[mfr.startIndex + 1]) << 8
    guard company == Self.companyId else { return }
    let data = mfr.subdata(in: (mfr.startIndex + 2)..<mfr.endIndex)
    if filtered && data.first != Self.protocolVersion { return }
    let rssi = RSSI.intValue
    if rssi == 127 { return } // "not available"
    seen[p.identifier] = p
    scanSink?([
      "address": p.identifier.uuidString,
      "rssi": rssi,
      "primaryPhy": 1,
      "secondaryPhy": 0,
      "legacy": true, // only the legacy 1M set reaches an iPhone
      "connectable": ad[CBAdvertisementDataIsConnectable] as? Bool ?? false,
      "txPower": (ad[CBAdvertisementDataTxPowerLevelKey] as? NSNumber)?.intValue ?? 127,
      "name": ad[CBAdvertisementDataLocalNameKey] as? String ?? p.name,
      "data": FlutterStandardTypedData(bytes: data),
    ])
  }

  func centralManagerDidUpdateState(_ central: CBCentralManager) {
    if CBManager.authorization != .notDetermined, !permissionWaiters.isEmpty {
      let ok = authorized
      permissionWaiters.forEach { $0(ok) }
      permissionWaiters.removeAll()
    }
    if central.state != .unknown && central.state != .resetting { flushAdapterWaiters() }
    let on = central.state == .poweredOn
    if on && wantScan && !central.isScanning {
      central.scanForPeripherals(withServices: nil, options: [CBCentralManagerScanOptionAllowDuplicatesKey: true])
    }
    // Peripheral objects die with the adapter: connect() retrieves them anew.
    if !on && central.state != .unknown { seen.removeAll() }
    if !on, let p = peripheral {
      failPending("Bluetooth выключен")
      bonding = false
      reconnect = false
      discovering = 0
      emitConn(["event": "state", "state": "disconnected", "address": p.identifier.uuidString, "status": -1])
      peripheral = nil
    }
    if central.state != .unknown && central.state != .resetting {
      emitConn(["event": "adapter", "enabled": on])
    }
  }

  // MARK: - GATT

  private func emitConn(_ m: [String: Any?]) { connSink?(m) }

  private func takePending() -> FlutterResult? {
    let r = pending
    pending = nil
    pendingKind = ""
    pendingUuid = nil
    return r
  }

  private func failPending(_ message: String) {
    takePending()?(FlutterError(code: "disconnected", message: message, details: nil))
  }

  private func connect(_ address: String, _ result: @escaping FlutterResult) {
    let c = manager()
    guard c.state == .poweredOn else {
      return result(FlutterError(code: "no_adapter", message: "Bluetooth недоступен", details: nil))
    }
    guard let id = UUID(uuidString: address),
          let p = seen[id] ?? c.retrievePeripherals(withIdentifiers: [id]).first else {
      return result(FlutterError(code: "unknown", message: "Маячок ещё не найден сканером", details: nil))
    }
    if let old = peripheral, old != p { c.cancelPeripheralConnection(old) }
    failPending("Новое соединение")
    bonding = false
    reconnect = false
    let reuse = p == peripheral && p.state == .connected
    peripheral = p
    p.delegate = self
    result(true)
    if p.state == .disconnecting {
      // The app disconnected and connects straight away (leaving the settings
      // page, "retry"): the pending didDisconnect belongs to the old link.
      reconnect = true
    } else if reuse {
      // The link is still open (the app only lost track of it after an
      // error): CoreBluetooth does not promise didConnect for a second
      // connect(), so answer from here.
      DispatchQueue.main.async { [weak self] in
        guard let self = self, p == self.peripheral, p.state == .connected else { return }
        self.emitConn(["event": "state", "state": "connected", "address": p.identifier.uuidString])
        if p.services != nil && self.discovering == 0 {
          self.ready(p)
        } else {
          self.discoverError = 0
          p.discoverServices(nil)
        }
      }
    } else {
      c.connect(p, options: nil)
    }
  }

  func centralManager(_ central: CBCentralManager, didConnect p: CBPeripheral) {
    guard p == peripheral else { return }
    emitConn(["event": "state", "state": "connected", "address": p.identifier.uuidString])
    discoverError = 0
    p.discoverServices(nil)
  }

  func centralManager(_ central: CBCentralManager, didFailToConnect p: CBPeripheral, error: Error?) {
    guard p == peripheral else { return }
    peripheral = nil
    emitConn(["event": "state", "state": "disconnected", "address": p.identifier.uuidString,
              "status": (error as NSError?)?.code ?? -1])
  }

  func centralManager(_ central: CBCentralManager, didDisconnectPeripheral p: CBPeripheral, error: Error?) {
    guard p == peripheral else { return }
    failPending("Соединение разорвано")
    if bonding {
      bonding = false
      emitConn(["event": "bond", "address": p.identifier.uuidString, "bond": "none",
                "status": attStatus(error)])
    }
    discovering = 0
    if reconnect {
      reconnect = false
      central.connect(p, options: nil)
      return
    }
    peripheral = nil
    emitConn(["event": "state", "state": "disconnected", "address": p.identifier.uuidString,
              "status": (error as NSError?)?.code ?? 0])
  }

  private var discovering = 0
  /// First error of the running discovery, reported with "ready" (0 = none).
  private var discoverError = 0

  func peripheral(_ p: CBPeripheral, didDiscoverServices error: Error?) {
    guard p == peripheral else { return }
    if error != nil && discoverError == 0 { discoverError = attStatus(error) }
    let services = p.services ?? []
    discovering = services.count
    if services.isEmpty {
      // A beacon without services is a failed discovery, not a ready link.
      if discoverError == 0 { discoverError = Self.failure }
      ready(p)
    }
    for s in services { p.discoverCharacteristics(nil, for: s) }
  }

  func peripheral(_ p: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
    guard p == peripheral, discovering > 0 else { return }
    if error != nil && discoverError == 0 { discoverError = attStatus(error) }
    discovering -= 1
    if discovering == 0 { ready(p) }
  }

  /// The beacon changed its GATT table (new firmware): the cached
  /// characteristics are dead. Drop the link, the app reconnects on the next
  /// action and discovers again.
  func peripheral(_ p: CBPeripheral, didModifyServices invalidatedServices: [CBService]) {
    guard p == peripheral else { return }
    central?.cancelPeripheralConnection(p)
  }

  private func ready(_ p: CBPeripheral) {
    guard p == peripheral else { return }
    emitConn(["event": "state", "state": "ready", "address": p.identifier.uuidString,
              "status": discoverError])
  }

  private func characteristic(_ uuid: String) -> CBCharacteristic? {
    let u = CBUUID(string: uuid)
    for s in peripheral?.services ?? [] {
      if let c = s.characteristics?.first(where: { $0.uuid == u }) { return c }
    }
    return nil
  }

  private func beginOp(_ kind: String, _ c: CBCharacteristic, _ result: @escaping FlutterResult) -> CBPeripheral? {
    guard let p = peripheral, p.state == .connected else {
      result(FlutterError(code: "not_connected", message: "Нет соединения", details: nil))
      return nil
    }
    if pending != nil {
      result(FlutterError(code: "busy", message: "GATT занят", details: nil))
      return nil
    }
    pending = result
    pendingKind = kind
    pendingUuid = c.uuid
    return p
  }

  private func noChar(_ uuid: String, _ result: FlutterResult) {
    result(FlutterError(code: "no_char", message: "Нет характеристики \(uuid)", details: nil))
  }

  private func read(_ uuid: String, _ result: @escaping FlutterResult) {
    guard let c = characteristic(uuid) else { return noChar(uuid, result) }
    guard let p = beginOp("read", c, result) else { return }
    p.readValue(for: c)
  }

  private func write(_ uuid: String, _ value: Data, _ result: @escaping FlutterResult) {
    guard let c = characteristic(uuid) else { return noChar(uuid, result) }
    guard let p = beginOp("write", c, result) else { return }
    p.writeValue(value, for: c, type: .withResponse)
  }

  private func setNotify(_ uuid: String, _ result: @escaping FlutterResult) {
    guard let c = characteristic(uuid) else { return noChar(uuid, result) }
    guard let p = beginOp("notify", c, result) else { return }
    p.setNotifyValue(true, for: c)
  }

  /// Pairing by touching the encrypted settings characteristic, see the class
  /// comment. The link must already be open (the app pairs inside _withLink).
  private func createBond(_ address: String, _ result: @escaping FlutterResult) {
    guard let p = peripheral, p.identifier.uuidString == address, p.state == .connected,
          let c = characteristic(Self.settingsUuid.uuidString) else {
      return result(false)
    }
    if pending != nil { return result(false) }
    bonding = true
    pendingKind = "bond"
    pendingUuid = c.uuid
    pending = { _ in }
    emitConn(["event": "bond", "address": address, "bond": "bonding"])
    p.readValue(for: c)
    result(true)
  }

  static let failure = 0x101 // GATT_FAILURE on Android

  /// Maps a CoreBluetooth error to an ATT status like Android's (0 = success).
  /// CBError codes (not ATT: lost pairing, encryption timeout, …) are passed
  /// as 0x200 + code, lib/protocol/cricket.dart turns them into text.
  private func attStatus(_ error: Error?) -> Int {
    guard let e = error as NSError? else { return 0 }
    if e.domain == CBATTErrorDomain { return e.code }
    if e.domain == CBErrorDomain { return 0x200 + e.code }
    return Self.failure
  }

  func peripheral(_ p: CBPeripheral, didUpdateValueFor c: CBCharacteristic, error: Error?) {
    guard p == peripheral else { return }
    if pendingKind == "bond" && c.uuid == pendingUuid {
      _ = takePending()
      bonding = false
      emitConn(["event": "bond", "address": p.identifier.uuidString,
                "bond": error == nil ? "bonded" : "none", "status": attStatus(error)])
      return
    }
    if pendingKind == "read" && c.uuid == pendingUuid {
      takePending()?(["status": attStatus(error), "value": FlutterStandardTypedData(bytes: c.value ?? Data())])
      return
    }
    // A notification.
    if error == nil {
      emitConn(["event": "notify", "uuid": c.uuid.uuidString.lowercased(),
                "value": FlutterStandardTypedData(bytes: c.value ?? Data())])
    }
  }

  func peripheral(_ p: CBPeripheral, didWriteValueFor c: CBCharacteristic, error: Error?) {
    guard p == peripheral else { return }
    if pendingKind == "write" && c.uuid == pendingUuid { takePending()?(attStatus(error)) }
  }

  func peripheral(_ p: CBPeripheral, didUpdateNotificationStateFor c: CBCharacteristic, error: Error?) {
    guard p == peripheral else { return }
    if pendingKind == "notify" && c.uuid == pendingUuid { takePending()?(attStatus(error)) }
  }

  // MARK: - Beep

  /// Short 2 kHz tone for the hot-cold finder; mixes with other audio and
  /// plays in silent mode, like a metal detector should.
  private func beep(ms: Int) {
    let format = AVAudioFormat(standardFormatWithSampleRate: 44100, channels: 1)!
    if !audioReady {
      try? AVAudioSession.sharedInstance().setCategory(.playback, options: [.mixWithOthers])
      audio.attach(player)
      audio.connect(player, to: audio.mainMixerNode, format: format)
      audioReady = true
    }
    if !audio.isRunning {
      try? AVAudioSession.sharedInstance().setActive(true)
      do { try audio.start() } catch { return }
    }
    // The engine costs power while it runs: stop it once the beeps end (the
    // slowest hot-cold rhythm is one beep in 1.5 s).
    audioIdle?.cancel()
    let idle = DispatchWorkItem { [weak self] in
      guard let self = self else { return }
      self.player.stop()
      self.audio.stop()
      try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }
    audioIdle = idle
    DispatchQueue.main.asyncAfter(deadline: .now() + 4, execute: idle)
    let frames = AVAudioFrameCount(Double(max(10, min(ms, 2000))) * 44.1)
    guard let buf = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frames) else { return }
    buf.frameLength = frames
    let s = buf.floatChannelData![0]
    let ramp = 220.0 // 5 ms fade in/out against clicks
    for i in 0..<Int(frames) {
      let env = min(1.0, Double(i) / ramp, Double(Int(frames) - i) / ramp)
      s[i] = Float(sin(2.0 * .pi * 2000.0 * Double(i) / 44100.0) * 0.6 * env)
    }
    player.scheduleBuffer(buf, at: nil, options: .interrupts)
    if !player.isPlaying { player.play() }
  }
}
