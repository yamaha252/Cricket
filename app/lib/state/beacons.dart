// Live list of Cricket beacons heard by the scanner.

import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../ble/ble.dart';
import '../protocol/cricket.dart';

class RssiPoint {
  RssiPoint(this.time, this.rssi, this.coded);
  final DateTime time;
  final int rssi;
  final bool coded;
}

class BeaconRecord {
  BeaconRecord(this.id);
  final int id;
  late CricketStatus status;
  String address = '';
  String? name;
  DateTime lastSeen = DateTime.fromMillisecondsSinceEpoch(0);
  int codedPackets = 0;
  int oneMPackets = 0;
  double? smoothRssi;
  final List<RssiPoint> history = [];

  Duration get age => DateTime.now().difference(lastSeen);
  bool get fresh => age < const Duration(seconds: 15);

  /// Median RSSI over the last [window]; null if nothing heard.
  double? medianRssi(Duration window) {
    final since = DateTime.now().subtract(window);
    final v = history.where((p) => p.time.isAfter(since)).map((p) => p.rssi).toList()..sort();
    if (v.isEmpty) return null;
    return v.length.isOdd ? v[v.length ~/ 2].toDouble() : (v[v.length ~/ 2 - 1] + v[v.length ~/ 2]) / 2;
  }

  double? get distanceM =>
      smoothRssi == null ? null : rssiToMeters(smoothRssi!, status.txAt1m);
}

enum ScanState { idle, noPermission, bluetoothOff, unsupported, scanning, failed }

class BeaconStore extends ChangeNotifier {
  BeaconStore() {
    _load();
  }

  final Map<int, BeaconRecord> beacons = {};

  /// Own beacons: id → label, kept on the phone.
  final Map<int, String> mine = {};

  ScanState state = ScanState.idle;
  String? error;
  AdapterInfo? adapter;

  /// Coded packets actually received: the support flag is unreliable
  /// (docs/app.md), so the app shows what really arrives.
  int codedTotal = 0;
  int oneMTotal = 0;

  StreamSubscription? _scanSub, _connSub;
  Timer? _notifyTimer, _rescanTimer;
  bool _dirty = false;
  int _ticks = 0;
  Future<void>? _starting;

  static const _prefsMine = 'mine_beacons';

  Future<void> _load() async {
    final p = await SharedPreferences.getInstance();
    final s = p.getString(_prefsMine);
    if (s == null) return;
    try {
      (jsonDecode(s) as Map).forEach((k, v) => mine[int.parse(k as String)] = v as String);
    } catch (e) {
      debugPrint('Own beacon list is damaged: $e');
    }
    notifyListeners();
  }

  Future<void> _saveMine() async {
    final p = await SharedPreferences.getInstance();
    await p.setString(_prefsMine, jsonEncode(mine.map((k, v) => MapEntry(k.toString(), v))));
  }

  void setMine(int id, String? label) {
    if (label == null) {
      mine.remove(id);
    } else {
      mine[id] = label;
    }
    _saveMine();
    notifyListeners();
  }

  String labelOf(int id) => mine[id] ?? beacons[id]?.name ?? formatId(id);

  List<BeaconRecord> get sorted {
    final l = beacons.values.toList();
    l.sort((a, b) {
      final am = mine.containsKey(a.id), bm = mine.containsKey(b.id);
      if (am != bm) return am ? -1 : 1;
      return (b.smoothRssi ?? -200).compareTo(a.smoothRssi ?? -200);
    });
    return l;
  }

  /// Starts scanning. With [request] false the permission dialog is not
  /// shown: used on resume, where asking again right after a refusal would
  /// put the dialog up twice in a row.
  Future<void> start({bool request = true}) {
    // Calls overlap (startup, resume, adapter events): run one at a time.
    final prev = _starting;
    late final Future<void> f;
    f = () async {
      if (prev != null) await prev;
      try {
        await _start(request);
      } finally {
        if (identical(_starting, f)) _starting = null;
      }
    }();
    return _starting = f;
  }

  Future<void> _start(bool request) async {
    if (state == ScanState.scanning) return;
    if (!await _permissions(request)) {
      state = ScanState.noPermission;
      notifyListeners();
      return;
    }
    try {
      adapter = await Ble.instance.adapterInfo();
    } catch (e) {
      state = ScanState.unsupported;
      error = '$e';
      notifyListeners();
      return;
    }
    if (!adapter!.present) {
      state = ScanState.unsupported;
    } else if (!adapter!.enabled) {
      state = ScanState.bluetoothOff;
    } else {
      _scanSub ??= Ble.instance.scanStream.listen(_onPacket, onError: (e) {
        state = ScanState.failed;
        error = '$e';
        notifyListeners();
      });
      try {
        state = await Ble.instance.startScan() ? ScanState.scanning : ScanState.failed;
        error = null;
      } catch (e) {
        state = ScanState.failed;
        error = '$e';
      }
    }
    _connSub ??= Ble.instance.connStream.listen((e) {
      if (e['event'] == 'adapter') {
        if (e['enabled'] == true) {
          start(request: false);
        } else {
          state = ScanState.bluetoothOff;
          notifyListeners();
        }
      }
    });
    _notifyTimer ??= Timer.periodic(const Duration(milliseconds: 300), (_) {
      // Without packets the screen still has to age: "no signal", "seen N s
      // ago" and the signal bars depend on the clock.
      final age = ++_ticks % 4 == 0 && beacons.isNotEmpty;
      if (_dirty || age) {
        _dirty = false;
        notifyListeners();
      }
    });
    // Android quietly downgrades a scan that runs for 30 min; a long search
    // would stop hearing the beacon, so the scan is restarted before that.
    _rescanTimer ??= Timer.periodic(const Duration(minutes: 20), (_) async {
      if (state != ScanState.scanning) return;
      try {
        if (!await Ble.instance.startScan()) {
          state = ScanState.failed;
          notifyListeners();
        }
      } catch (e) {
        state = ScanState.failed;
        error = '$e';
        notifyListeners();
      }
    });
    notifyListeners();
  }

  Future<void> stop() async {
    if (state == ScanState.scanning) {
      await Ble.instance.stopScan();
      state = ScanState.idle;
      notifyListeners();
    }
  }

  Future<bool> _permissions(bool request) async {
    try {
      return request
          ? await Ble.instance.requestPermissions()
          : await Ble.instance.hasPermissions();
    } catch (_) {
      return false; // no native layer (iOS not done yet)
    }
  }

  void _onPacket(ScanPacket p) {
    final st = CricketStatus.parse(p.data);
    if (st == null) return;
    final r = beacons.putIfAbsent(st.id, () => BeaconRecord(st.id));
    r.status = st;
    r.address = p.address;
    if (p.name != null && p.name!.isNotEmpty) r.name = p.name;
    r.lastSeen = p.time;
    if (p.coded) {
      r.codedPackets++;
      codedTotal++;
    } else {
      r.oneMPackets++;
      oneMTotal++;
    }
    r.smoothRssi = r.smoothRssi == null ? p.rssi.toDouble() : r.smoothRssi! * 0.7 + p.rssi * 0.3;
    r.history.add(RssiPoint(p.time, p.rssi, p.coded));
    final cut = p.time.subtract(const Duration(minutes: 2));
    while (r.history.isNotEmpty && r.history.first.time.isBefore(cut)) {
      r.history.removeAt(0);
    }
    _dirty = true;
  }

  @override
  void dispose() {
    _scanSub?.cancel();
    _connSub?.cancel();
    _notifyTimer?.cancel();
    _rescanTimer?.cancel();
    super.dispose();
  }
}
