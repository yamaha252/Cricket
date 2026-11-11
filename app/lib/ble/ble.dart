// Dart side of the native BLE layer (android/.../CricketBle.kt).

import 'dart:async';

import 'package:flutter/services.dart';

const int phy1M = 1;
const int phyCoded = 3;

class ScanPacket {
  ScanPacket({
    required this.address,
    required this.rssi,
    required this.primaryPhy,
    required this.secondaryPhy,
    required this.legacy,
    required this.connectable,
    required this.name,
    required this.data,
    required this.time,
  });

  final String address;
  final int rssi;
  final int primaryPhy;
  final int secondaryPhy;
  final bool legacy;
  final bool connectable;
  final String? name;
  final Uint8List data; // manufacturer data after the Company ID
  final DateTime time;

  bool get coded => primaryPhy == phyCoded;

  factory ScanPacket.fromMap(Map m) => ScanPacket(
        address: m['address'] as String,
        rssi: m['rssi'] as int,
        primaryPhy: m['primaryPhy'] as int? ?? phy1M,
        secondaryPhy: m['secondaryPhy'] as int? ?? 0,
        legacy: m['legacy'] as bool? ?? true,
        connectable: m['connectable'] as bool? ?? false,
        name: m['name'] as String?,
        data: m['data'] as Uint8List,
        time: DateTime.now(),
      );
}

class AdapterInfo {
  AdapterInfo(Map m)
      : present = m['present'] as bool? ?? false,
        enabled = m['enabled'] as bool? ?? false,
        codedSupported = m['codedSupported'] as bool? ?? false,
        extendedSupported = m['extendedSupported'] as bool? ?? false,
        model = m['model'] as String? ?? '';
  final bool present, enabled, codedSupported, extendedSupported;
  final String model;
}

class BleException implements Exception {
  BleException(this.message, {this.status});
  final String message;

  /// GATT status when the beacon answered with an error.
  final int? status;
  @override
  String toString() => message;
}

/// Thin wrapper over the platform channels. GATT calls are serialised here,
/// Android allows one outstanding operation per connection.
class Ble {
  Ble._();
  static final Ble instance = Ble._();

  static const _m = MethodChannel('cricket/ble');
  static const _scan = EventChannel('cricket/scan');
  static const _conn = EventChannel('cricket/conn');

  late final Stream<ScanPacket> scanStream =
      _scan.receiveBroadcastStream().map((e) => ScanPacket.fromMap(e as Map)).asBroadcastStream();
  late final Stream<Map> connStream =
      _conn.receiveBroadcastStream().map((e) => e as Map).asBroadcastStream();

  Future<void> _queue = Future.value();

  Future<T> _serial<T>(Future<T> Function() f) {
    final c = Completer<T>();
    _queue = _queue.then((_) async {
      try {
        c.complete(await f());
      } catch (e, s) {
        c.completeError(e, s);
      }
    });
    return c.future;
  }

  Future<AdapterInfo> adapterInfo() async =>
      AdapterInfo(await _m.invokeMethod<Map>('adapterInfo') ?? {});
  Future<bool> hasPermissions() async => await _m.invokeMethod<bool>('hasPermissions') ?? false;
  Future<bool> requestPermissions() async =>
      await _m.invokeMethod<bool>('requestPermissions') ?? false;
  Future<void> openAppSettings() => _m.invokeMethod('openAppSettings');
  Future<void> requestEnable() => _m.invokeMethod('requestEnable');
  Future<bool> startScan({bool filtered = true}) async =>
      await _m.invokeMethod<bool>('startScan', {'filtered': filtered}) ?? false;
  Future<void> stopScan() => _m.invokeMethod('stopScan');
  // Fire-and-forget conveniences: a failure here must not surface as an
  // unhandled error (no native layer, ToneGenerator refused).
  Future<void> keepScreenOn(bool on) =>
      _m.invokeMethod('keepScreenOn', {'on': on}).catchError((_) {});
  Future<void> beep([int ms = 60]) => _m.invokeMethod('beep', {'ms': ms}).catchError((_) {});
  Future<bool> createBond(String address) async =>
      await _m.invokeMethod<bool>('createBond', {'address': address}) ?? false;
  Future<String> bondState(String address) async =>
      await _m.invokeMethod<String>('bondState', {'address': address}) ?? 'none';

  /// Connects and waits until services are discovered. Android often fails
  /// the first attempt with status 133, so that one is retried once.
  Future<void> connect(String address, {Duration timeout = const Duration(seconds: 20)}) async {
    for (var attempt = 0;; attempt++) {
      final ready = connStream
          .where((e) => e['event'] == 'state' && e['address'] == address)
          .firstWhere((e) => e['state'] == 'ready' || e['state'] == 'disconnected')
          .timeout(timeout);
      ready.ignore(); // errors are handled by the await below
      final Map e;
      try {
        await _m.invokeMethod('connect', {'address': address});
        e = await ready;
      } on PlatformException catch (err) {
        throw BleException(err.message ?? err.code);
      } on TimeoutException {
        await disconnect();
        throw BleException('Маячок не отвечает');
      }
      if (e['state'] == 'ready') {
        if (e['status'] == 0) return;
        await disconnect();
        throw BleException('Сервисы маячка не прочитаны (${e['status']})');
      }
      if (e['status'] == 133 && attempt == 0) continue;
      throw BleException('Соединение разорвано (${e['status']})');
    }
  }

  Future<void> disconnect() => _m.invokeMethod('disconnect').catchError((_) {});

  Future<Uint8List> read(String uuid) => _serial(() async {
        final r = await _call<Map>('read', {'uuid': uuid});
        final status = r['status'] as int;
        if (status != 0) throw BleException('Чтение: статус $status', status: status);
        return r['value'] as Uint8List;
      });

  /// Returns the GATT status (0 = success).
  Future<int> write(String uuid, Uint8List value) =>
      _serial(() => _call<int>('write', {'uuid': uuid, 'value': value}));

  Future<int> enableNotify(String uuid) => _serial(() => _call<int>('notify', {'uuid': uuid}));

  Future<T> _call<T>(String method, Map args) async {
    try {
      final r = await _m.invokeMethod<T>(method, args).timeout(const Duration(seconds: 15));
      return r as T;
    } on PlatformException catch (e) {
      throw BleException(e.message ?? e.code);
    } on TimeoutException {
      // The native side still holds the operation; dropping the link frees it,
      // otherwise every later call would answer "busy".
      await disconnect();
      throw BleException('Нет ответа от маячка');
    }
  }
}
