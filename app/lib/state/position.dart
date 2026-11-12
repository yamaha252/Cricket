// Phone GPS position. Works without network: Android uses GNSS directly,
// iOS Core Location works offline by itself.

import 'dart:async';
import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';
import 'package:geolocator/geolocator.dart';

class PositionService extends ChangeNotifier {
  Position? last;

  /// When [last] arrived, by the phone's clock.
  DateTime? lastTime;
  String? error;
  StreamSubscription<Position>? _sub;
  StreamSubscription<ServiceStatus>? _serviceSub;

  static const _disabledText = 'Геолокация выключена';
  static const _deniedText = 'Нет разрешения на геолокацию';

  bool _starting = false;

  /// The user gave only approximate location (iOS «Точная геопозиция» off,
  /// Android "approximate"): kilometres of error, useless for the bearing.
  bool reduced = false;
  static const _reducedText =
      'Геолокация приблизительная: пеленг не работает. Включите точную геопозицию для Cricket в настройках телефона';

  Future<void> _checkAccuracy() async {
    try {
      reduced = await Geolocator.getLocationAccuracy() == LocationAccuracyStatus.reduced;
    } catch (_) {
      reduced = false;
    }
    if (reduced) {
      error = _reducedText;
    } else if (error == _reducedText) {
      error = null;
    }
    notifyListeners();
  }

  /// With [request] false the permission dialog is not shown (used on
  /// resume, to pick up a permission granted in the system settings).
  Future<void> start({bool request = true}) async {
    if (_starting) return;
    if (_sub != null) return _checkAccuracy(); // may have changed in settings
    _starting = true;
    try {
      await _start(request);
    } catch (e) {
      error = '$e';
      notifyListeners();
    } finally {
      _starting = false;
    }
  }

  Future<void> _start(bool request) async {
    // Location switched on from the quick settings does not resume the app:
    // this is the only signal to start again.
    try {
      _serviceSub ??= Geolocator.getServiceStatusStream().listen((s) {
        if (s == ServiceStatus.enabled) start(request: false);
      }, onError: (_) {});
    } catch (_) {}
    var p = await Geolocator.checkPermission();
    if (p == LocationPermission.denied && request) p = await Geolocator.requestPermission();
    if (p == LocationPermission.denied || p == LocationPermission.deniedForever) {
      error = _deniedText;
      notifyListeners();
      return;
    }
    if (!await Geolocator.isLocationServiceEnabled()) {
      // A stream opened now would fail once and stay dead.
      error = _disabledText;
      notifyListeners();
      return;
    }
    await _checkAccuracy();
    _sub = Geolocator.getPositionStream(
      locationSettings: Platform.isIOS
          ? AppleSettings(
              accuracy: LocationAccuracy.best,
              distanceFilter: 0,
              activityType: ActivityType.otherNavigation,
              // Standing still while listening for the beacon is normal.
              pauseLocationUpdatesAutomatically: false,
            )
          : AndroidSettings(
              accuracy: LocationAccuracy.best,
              distanceFilter: 0,
              intervalDuration: const Duration(seconds: 1),
              // Plain LocationManager: GNSS without Play services or network.
              forceLocationManager: true,
            ),
    ).listen((pos) {
      last = pos;
      lastTime = DateTime.now();
      error = reduced ? _reducedText : null;
      notifyListeners();
    }, onError: (Object e) {
      // The plugin stops its updates on an error (location switched off):
      // drop the stream so that the next start() opens a new one.
      _sub?.cancel();
      _sub = null;
      error = e is LocationServiceDisabledException
          ? _disabledText
          : e is PermissionDeniedException
              ? _deniedText
              : '$e';
      notifyListeners();
    });
  }

  /// Tap on the error banner: asks for the permission again or opens the
  /// system page where the user can fix what [error] says.
  Future<void> resolve() async {
    try {
      var p = await Geolocator.checkPermission();
      if (p == LocationPermission.denied) {
        await start();
        p = await Geolocator.checkPermission();
      }
      if (p == LocationPermission.denied || p == LocationPermission.deniedForever || reduced) {
        await Geolocator.openAppSettings();
      } else if (!await Geolocator.isLocationServiceEnabled()) {
        await Geolocator.openLocationSettings();
      } else {
        await start(request: false);
      }
    } catch (_) {}
  }

  @override
  void dispose() {
    _sub?.cancel();
    _serviceSub?.cancel();
    super.dispose();
  }
}
