package dev.cricket.cricket

import android.annotation.SuppressLint
import android.app.Activity
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.media.AudioManager
import android.media.ToneGenerator
import android.Manifest
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.os.Handler
import android.os.Looper
import android.view.WindowManager
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import java.util.UUID

/**
 * Own BLE layer for Cricket (no third-party BLE plugin).
 *
 * Scanning uses PHY_LE_ALL_SUPPORTED with legacy off: on Pixel phones a Coded-only
 * scan returns just 1M packets, scanning both PHYs at once delivers Coded ones too
 * (docs/app.md). One GATT connection at a time, one GATT operation at a time;
 * the Dart side serialises calls.
 */
@SuppressLint("MissingPermission") // permissions are requested on the Dart side
class CricketBle(private val activity: Activity, messenger: BinaryMessenger) :
    MethodChannel.MethodCallHandler {

    companion object {
        const val PERMISSION_REQUEST = 0xC1
        const val COMPANY_ID = 0xFFFF
        const val PROTOCOL_VERSION: Byte = 2
        val CCCD: UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
    }

    private val ctx: Context = activity.applicationContext
    private val manager = ctx.getSystemService(BluetoothManager::class.java)
    private val adapter: BluetoothAdapter? get() = manager?.adapter
    private val main = Handler(Looper.getMainLooper())

    private var scanSink: EventChannel.EventSink? = null
    private var connSink: EventChannel.EventSink? = null
    private var scanning = false

    private var gatt: BluetoothGatt? = null
    private var pending: MethodChannel.Result? = null
    private var tone: ToneGenerator? = null
    private var permissionResult: MethodChannel.Result? = null

    private fun neededPermissions(): Array<String> =
        if (Build.VERSION.SDK_INT >= 31) arrayOf(
            Manifest.permission.BLUETOOTH_SCAN,
            Manifest.permission.BLUETOOTH_CONNECT,
            Manifest.permission.ACCESS_FINE_LOCATION,
        ) else arrayOf(Manifest.permission.ACCESS_FINE_LOCATION)

    private fun hasPermissions() = neededPermissions().all {
        activity.checkSelfPermission(it) == PackageManager.PERMISSION_GRANTED
    }

    /** Forwarded from MainActivity.onRequestPermissionsResult. */
    fun onPermissionsResult(requestCode: Int) {
        if (requestCode == PERMISSION_REQUEST) permissionResult?.success(hasPermissions())
        permissionResult = null
    }

    private val receiver = object : BroadcastReceiver() {
        override fun onReceive(c: Context?, intent: Intent?) {
            when (intent?.action) {
                BluetoothDevice.ACTION_BOND_STATE_CHANGED -> {
                    val dev: BluetoothDevice? = if (Build.VERSION.SDK_INT >= 33)
                        intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE, BluetoothDevice::class.java)
                    else @Suppress("DEPRECATION") intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE)
                    val state = intent.getIntExtra(BluetoothDevice.EXTRA_BOND_STATE, BluetoothDevice.BOND_NONE)
                    emitConn(mapOf("event" to "bond", "address" to dev?.address, "bond" to bondName(state)))
                }
                BluetoothAdapter.ACTION_STATE_CHANGED -> {
                    val state = intent.getIntExtra(BluetoothAdapter.EXTRA_STATE, BluetoothAdapter.STATE_OFF)
                    if (state != BluetoothAdapter.STATE_ON) scanning = false
                    emitConn(mapOf("event" to "adapter", "enabled" to (state == BluetoothAdapter.STATE_ON)))
                }
            }
        }
    }

    init {
        MethodChannel(messenger, "cricket/ble").setMethodCallHandler(this)
        EventChannel(messenger, "cricket/scan").setStreamHandler(object : EventChannel.StreamHandler {
            override fun onListen(args: Any?, sink: EventChannel.EventSink?) { scanSink = sink }
            override fun onCancel(args: Any?) { scanSink = null }
        })
        EventChannel(messenger, "cricket/conn").setStreamHandler(object : EventChannel.StreamHandler {
            override fun onListen(args: Any?, sink: EventChannel.EventSink?) { connSink = sink }
            override fun onCancel(args: Any?) { connSink = null }
        })
        val filter = IntentFilter().apply {
            addAction(BluetoothDevice.ACTION_BOND_STATE_CHANGED)
            addAction(BluetoothAdapter.ACTION_STATE_CHANGED)
        }
        if (Build.VERSION.SDK_INT >= 33) {
            // System broadcasts are still delivered; other apps cannot fake them.
            ctx.registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            ctx.registerReceiver(receiver, filter)
        }
    }

    fun dispose() {
        stopScan()
        gatt?.close()
        gatt = null
        tone?.release()
        tone = null
        try { ctx.unregisterReceiver(receiver) } catch (_: Exception) {}
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        try {
            when (call.method) {
                "adapterInfo" -> result.success(adapterInfo())
                "hasPermissions" -> result.success(hasPermissions())
                "requestPermissions" -> {
                    if (hasPermissions()) return result.success(true)
                    permissionResult?.success(false)
                    permissionResult = result
                    activity.requestPermissions(neededPermissions(), PERMISSION_REQUEST)
                }
                "openAppSettings" -> {
                    activity.startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                        Uri.fromParts("package", activity.packageName, null)))
                    result.success(null)
                }
                "requestEnable" -> {
                    activity.startActivity(Intent(BluetoothAdapter.ACTION_REQUEST_ENABLE))
                    result.success(null)
                }
                "startScan" -> result.success(startScan(call.argument<Boolean>("filtered") ?: true))
                "stopScan" -> { stopScan(); result.success(null) }
                "connect" -> connect(call.argument<String>("address")!!, result)
                "disconnect" -> { gatt?.disconnect(); result.success(null) }
                "read" -> read(call.argument<String>("uuid")!!, result)
                "write" -> write(call.argument<String>("uuid")!!, call.argument<ByteArray>("value")!!, result)
                "notify" -> setNotify(call.argument<String>("uuid")!!, result)
                "createBond" -> result.success(adapter?.getRemoteDevice(call.argument<String>("address")!!)?.createBond() ?: false)
                "bondState" -> {
                    val dev = adapter?.getRemoteDevice(call.argument<String>("address")!!)
                    result.success(bondName(dev?.bondState ?: BluetoothDevice.BOND_NONE))
                }
                "keepScreenOn" -> {
                    if (call.argument<Boolean>("on") == true) activity.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                    else activity.window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                    result.success(null)
                }
                "beep" -> {
                    if (tone == null) tone = ToneGenerator(AudioManager.STREAM_MUSIC, 90)
                    tone?.startTone(ToneGenerator.TONE_PROP_BEEP, call.argument<Int>("ms") ?: 60)
                    result.success(null)
                }
                else -> result.notImplemented()
            }
        } catch (e: SecurityException) {
            result.error("permission", e.message, null)
        } catch (e: Exception) {
            result.error("error", e.message, null)
        }
    }

    private fun adapterInfo(): Map<String, Any?> {
        val a = adapter
        return mapOf(
            "present" to (a != null),
            "enabled" to (a?.isEnabled == true),
            "codedSupported" to (a?.isLeCodedPhySupported == true),
            "extendedSupported" to (a?.isLeExtendedAdvertisingSupported == true),
            "sdk" to Build.VERSION.SDK_INT,
            "model" to Build.MODEL,
        )
    }

    // ---------------------------------------------------------------- scanning

    private val scanCb = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, r: ScanResult) = emitScan(r)
        override fun onBatchScanResults(results: MutableList<ScanResult>) = results.forEach(::emitScan)
        override fun onScanFailed(errorCode: Int) {
            scanning = false
            main.post { scanSink?.error("scan_failed", "Scan failed, code $errorCode", errorCode) }
        }
    }

    private fun emitScan(r: ScanResult) {
        val rec = r.scanRecord ?: return
        val data = rec.getManufacturerSpecificData(COMPANY_ID) ?: return
        val m = hashMapOf<String, Any?>(
            "address" to r.device.address,
            "rssi" to r.rssi,
            "primaryPhy" to r.primaryPhy,     // 1 = 1M, 3 = Coded
            "secondaryPhy" to r.secondaryPhy, // 0 = none (legacy)
            "legacy" to r.isLegacy,
            "connectable" to r.isConnectable,
            "txPower" to r.txPower,           // 127 = not present
            "name" to rec.deviceName,
            "data" to data,
        )
        main.post { scanSink?.success(m) }
    }

    private fun startScan(filtered: Boolean): Boolean {
        val scanner = adapter?.bluetoothLeScanner ?: return false
        if (scanning) scanner.stopScan(scanCb)
        val settings = ScanSettings.Builder()
            .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
            .setLegacy(false)
            .setPhy(ScanSettings.PHY_LE_ALL_SUPPORTED)
            .setReportDelay(0)
            .build()
        val filters = if (filtered) listOf(
            ScanFilter.Builder()
                .setManufacturerData(COMPANY_ID, byteArrayOf(PROTOCOL_VERSION), byteArrayOf(0xFF.toByte()))
                .build()
        ) else emptyList()
        scanner.startScan(filters, settings, scanCb)
        scanning = true
        return true
    }

    private fun stopScan() {
        if (!scanning) return
        scanning = false
        try { adapter?.bluetoothLeScanner?.stopScan(scanCb) } catch (_: Exception) {}
    }

    // ---------------------------------------------------------------- GATT

    private fun emitConn(m: Map<String, Any?>) = main.post { connSink?.success(m) }

    private fun takePending(): MethodChannel.Result? = pending.also { pending = null }

    private fun connect(address: String, result: MethodChannel.Result) {
        val a = adapter ?: return result.error("no_adapter", "Bluetooth unavailable", null)
        gatt?.close()
        pending?.error("cancelled", "New connection", null)
        pending = null
        val dev = a.getRemoteDevice(address)
        gatt = dev.connectGatt(ctx, false, gattCb, BluetoothDevice.TRANSPORT_LE,
            BluetoothDevice.PHY_LE_1M_MASK or BluetoothDevice.PHY_LE_CODED_MASK)
        result.success(gatt != null)
    }

    private fun characteristic(uuid: String): BluetoothGattCharacteristic? {
        val u = UUID.fromString(uuid)
        return gatt?.services?.firstNotNullOfOrNull { it.getCharacteristic(u) }
    }

    private fun beginOp(result: MethodChannel.Result): Boolean {
        if (gatt == null) { result.error("not_connected", "Not connected", null); return false }
        if (pending != null) { result.error("busy", "GATT operation in progress", null); return false }
        pending = result
        return true
    }

    private fun read(uuid: String, result: MethodChannel.Result) {
        val c = characteristic(uuid) ?: return result.error("no_char", "No characteristic $uuid", null)
        if (!beginOp(result)) return
        if (gatt?.readCharacteristic(c) != true) takePending()?.error("failed", "readCharacteristic refused", null)
    }

    private fun write(uuid: String, value: ByteArray, result: MethodChannel.Result) {
        val c = characteristic(uuid) ?: return result.error("no_char", "No characteristic $uuid", null)
        if (!beginOp(result)) return
        val ok = if (Build.VERSION.SDK_INT >= 33) {
            gatt?.writeCharacteristic(c, value, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT) == BluetoothGatt.GATT_SUCCESS
        } else {
            @Suppress("DEPRECATION")
            run {
                c.writeType = BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
                c.value = value
                gatt?.writeCharacteristic(c) == true
            }
        }
        if (!ok) takePending()?.error("failed", "writeCharacteristic refused", null)
    }

    private fun setNotify(uuid: String, result: MethodChannel.Result) {
        val g = gatt ?: return result.error("not_connected", "Not connected", null)
        val c = characteristic(uuid) ?: return result.error("no_char", "No characteristic $uuid", null)
        val d = c.getDescriptor(CCCD) ?: return result.error("no_cccd", "No CCCD", null)
        g.setCharacteristicNotification(c, true)
        if (!beginOp(result)) return
        val v = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
        val ok = if (Build.VERSION.SDK_INT >= 33) {
            g.writeDescriptor(d, v) == BluetoothGatt.GATT_SUCCESS
        } else {
            @Suppress("DEPRECATION")
            run { d.value = v; g.writeDescriptor(d) }
        }
        if (!ok) takePending()?.error("failed", "writeDescriptor refused", null)
    }

    private val gattCb = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(g: BluetoothGatt, status: Int, newState: Int) {
            main.post {
                if (g != gatt) { g.close(); return@post }
                when (newState) {
                    BluetoothProfile.STATE_CONNECTED -> {
                        emitConn(mapOf("event" to "state", "state" to "connected", "address" to g.device.address))
                        if (!g.requestMtu(185)) g.discoverServices()
                    }
                    BluetoothProfile.STATE_DISCONNECTED -> {
                        takePending()?.error("disconnected", "Disconnected", status)
                        g.close()
                        gatt = null
                        emitConn(mapOf("event" to "state", "state" to "disconnected",
                            "address" to g.device.address, "status" to status))
                    }
                }
            }
        }

        override fun onMtuChanged(g: BluetoothGatt, mtu: Int, status: Int) {
            main.post { if (g == gatt) g.discoverServices() }
        }

        override fun onPhyUpdate(g: BluetoothGatt, txPhy: Int, rxPhy: Int, status: Int) {
            emitConn(mapOf("event" to "phy", "tx" to txPhy, "rx" to rxPhy))
        }

        override fun onServicesDiscovered(g: BluetoothGatt, status: Int) {
            main.post {
                if (g != gatt) return@post
                emitConn(mapOf("event" to "state", "state" to "ready", "address" to g.device.address, "status" to status))
                g.readPhy()
            }
        }

        override fun onCharacteristicRead(g: BluetoothGatt, c: BluetoothGattCharacteristic, value: ByteArray, status: Int) {
            main.post { takePending()?.success(mapOf("status" to status, "value" to value)) }
        }

        @Deprecated("API < 33")
        @Suppress("DEPRECATION")
        override fun onCharacteristicRead(g: BluetoothGatt, c: BluetoothGattCharacteristic, status: Int) {
            if (Build.VERSION.SDK_INT >= 33) return
            val v = c.value ?: ByteArray(0)
            main.post { takePending()?.success(mapOf("status" to status, "value" to v)) }
        }

        override fun onCharacteristicWrite(g: BluetoothGatt, c: BluetoothGattCharacteristic, status: Int) {
            main.post { takePending()?.success(status) }
        }

        override fun onDescriptorWrite(g: BluetoothGatt, d: BluetoothGattDescriptor, status: Int) {
            main.post { takePending()?.success(status) }
        }

        override fun onCharacteristicChanged(g: BluetoothGatt, c: BluetoothGattCharacteristic, value: ByteArray) {
            emitConn(mapOf("event" to "notify", "uuid" to c.uuid.toString(), "value" to value))
        }

        @Deprecated("API < 33")
        @Suppress("DEPRECATION")
        override fun onCharacteristicChanged(g: BluetoothGatt, c: BluetoothGattCharacteristic) {
            if (Build.VERSION.SDK_INT >= 33) return
            emitConn(mapOf("event" to "notify", "uuid" to c.uuid.toString(), "value" to (c.value ?: ByteArray(0))))
        }
    }

    private fun bondName(state: Int) = when (state) {
        BluetoothDevice.BOND_BONDED -> "bonded"
        BluetoothDevice.BOND_BONDING -> "bonding"
        else -> "none"
    }
}
