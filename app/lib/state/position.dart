// Phone GPS position. Works without network: Android uses GNSS directly.

import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:geolocator/geolocator.dart';

class PositionService extends ChangeNotifier {
  Position? last;
  String? error;
  StreamSubscription<Position>? _sub;

  Future<void> start() async {
    if (_sub != null) return;
    if (!await Geolocator.isLocationServiceEnabled()) {
      error = 'Геолокация выключена';
      notifyListeners();
    }
    var p = await Geolocator.checkPermission();
    if (p == LocationPermission.denied) p = await Geolocator.requestPermission();
    if (p == LocationPermission.denied || p == LocationPermission.deniedForever) {
      error = 'Нет разрешения на геолокацию';
      notifyListeners();
      return;
    }
    _sub = Geolocator.getPositionStream(
      locationSettings: AndroidSettings(
        accuracy: LocationAccuracy.best,
        distanceFilter: 0,
        intervalDuration: const Duration(seconds: 1),
        // Plain LocationManager: GNSS without Play services or network.
        forceLocationManager: true,
      ),
    ).listen((pos) {
      last = pos;
      error = null;
      notifyListeners();
    }, onError: (e) {
      error = '$e';
      notifyListeners();
    });
  }

  @override
  void dispose() {
    _sub?.cancel();
    super.dispose();
  }
}
