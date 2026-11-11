// Where is the beacon: pairs "phone GPS + RSSI" collected while the owner walks,
// fitted to the log-distance path-loss model by weighted least squares on a grid
// (docs/app.md, function 3). Works fully offline.

import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/foundation.dart';
import 'package:latlong2/latlong.dart';

import 'beacons.dart';
import 'position.dart';

class Sample {
  Sample(this.lat, this.lon, this.rssi, this.accuracyM, this.time);
  final double lat, lon, rssi, accuracyM;
  final DateTime time;
}

class Cell {
  Cell(this.center, this.halfSizeM, this.likelihood);
  final LatLng center;
  final double halfSizeM;
  final double likelihood; // 0..1, 1 = best
}

class Estimate {
  Estimate(this.best, this.radiusM, this.cells, this.p0, this.samples);
  final LatLng best;
  final double radiusM;
  final List<Cell> cells;
  final double p0;
  final int samples;
}

const double _mPerDegLat = 111320.0;

/// Grid search of the weighted least-squares cost
///   Σ wᵢ (rssiᵢ − (P0 − 10·n·log10 dᵢ))² + k (P0 − prior)²
/// where P0 (RSSI at 1 m) has a closed-form optimum per cell. Returns null
/// with fewer than 4 samples or when they span less than 10 m.
Estimate? estimate(List<Sample> samples, {double n = 2.2, double priorP0 = -59, int grid = 70}) {
  if (samples.length < 4) return null;
  final lat0 = samples.first.lat, lon0 = samples.first.lon;
  final mPerDegLon = _mPerDegLat * math.cos(lat0 * math.pi / 180);
  final xs = [for (final s in samples) (s.lon - lon0) * mPerDegLon];
  final ys = [for (final s in samples) (s.lat - lat0) * _mPerDegLat];
  final ws = [for (final s in samples) 1 / (1 + (s.accuracyM / 10) * (s.accuracyM / 10))];
  var minX = xs.reduce(math.min), maxX = xs.reduce(math.max);
  var minY = ys.reduce(math.min), maxY = ys.reduce(math.max);
  final span = math.max(maxX - minX, maxY - minY);
  if (span < 10) return null;
  final margin = math.max(150.0, span);
  minX -= margin;
  maxX += margin;
  minY -= margin;
  maxY += margin;
  final size = math.max(maxX - minX, maxY - minY);
  final step = size / grid;
  const sigma = 6.0; // dB, RSSI scatter
  const k = (sigma * sigma) / (10.0 * 10.0); // prior on P0 with σ = 10 dB
  final sumW = ws.reduce((a, b) => a + b);

  final costs = List<double>.filled(grid * grid, 0);
  final p0s = List<double>.filled(grid * grid, 0);
  var best = 0;
  final r = List<double>.filled(samples.length, 0);
  for (var gy = 0; gy < grid; gy++) {
    final cy = minY + (gy + 0.5) * step;
    for (var gx = 0; gx < grid; gx++) {
      final cx = minX + (gx + 0.5) * step;
      var sumWR = 0.0;
      for (var i = 0; i < samples.length; i++) {
        final dx = xs[i] - cx, dy = ys[i] - cy;
        final d = math.max(1.0, math.sqrt(dx * dx + dy * dy));
        r[i] = samples[i].rssi + 10 * n * math.log(d) / math.ln10;
        sumWR += ws[i] * r[i];
      }
      final p0 = (sumWR + k * priorP0) / (sumW + k);
      var c = k * (p0 - priorP0) * (p0 - priorP0);
      for (var i = 0; i < samples.length; i++) {
        final e = r[i] - p0;
        c += ws[i] * e * e;
      }
      final idx = gy * grid + gx;
      costs[idx] = c;
      p0s[idx] = p0;
      if (c < costs[best]) best = idx;
    }
  }

  // Scale the cost so that the likelihood reflects the effective sample count.
  final minCost = costs[best];
  LatLng toLatLng(double x, double y) => LatLng(lat0 + y / _mPerDegLat, lon0 + x / mPerDegLon);
  final bx = minX + (best % grid + 0.5) * step, by = minY + (best ~/ grid + 0.5) * step;
  final cells = <Cell>[];
  var sumL = 0.0, sumLd2 = 0.0;
  for (var idx = 0; idx < costs.length; idx++) {
    final l = math.exp(-(costs[idx] - minCost) / (2 * sigma * sigma));
    if (l < 0.02) continue;
    final x = minX + (idx % grid + 0.5) * step, y = minY + (idx ~/ grid + 0.5) * step;
    sumL += l;
    sumLd2 += l * ((x - bx) * (x - bx) + (y - by) * (y - by));
    if (l >= 0.05) cells.add(Cell(toLatLng(x, y), step / 2, l));
  }
  final radius = math.max(step, math.sqrt(sumLd2 / sumL));
  return Estimate(toLatLng(bx, by), radius, cells, p0s[best], samples.length);
}

/// The fit runs on the UI thread and costs grid² × samples, so a long walk
/// (one sample a second) is thinned evenly to at most [max] samples.
List<Sample> thin(List<Sample> samples, {int max = 600}) {
  if (samples.length <= max) return samples;
  return [for (var i = 0; i < max; i++) samples[i * samples.length ~/ max]];
}

/// Records samples for the selected beacon while it is heard and the phone
/// has a GPS fix.
class LocatorService extends ChangeNotifier {
  LocatorService(this.beacons, this.position) {
    position.addListener(_onPosition);
  }

  final BeaconStore beacons;
  final PositionService position;

  int? target;
  bool recording = false;
  final Map<int, List<Sample>> samples = {};
  Estimate? result;
  DateTime _lastSample = DateTime.fromMillisecondsSinceEpoch(0);
  Timer? _recalc;

  List<Sample> get current => target == null ? const [] : (samples[target!] ?? const []);

  void select(int id) {
    if (target != id) {
      target = id;
      result = null;
      _schedule();
    }
    notifyListeners();
  }

  void setRecording(bool on) {
    recording = on;
    notifyListeners();
  }

  void clear() {
    if (target != null) samples.remove(target);
    result = null;
    notifyListeners();
  }

  void _onPosition() {
    if (!recording || target == null) return;
    final pos = position.last;
    final rec = beacons.beacons[target];
    if (pos == null || rec == null) return;
    final now = DateTime.now();
    if (now.difference(_lastSample) < const Duration(seconds: 1)) return;
    if (pos.accuracy > 30) return;
    final rssi = rec.medianRssi(const Duration(seconds: 2));
    if (rssi == null) return;
    _lastSample = now;
    (samples[target!] ??= []).add(Sample(pos.latitude, pos.longitude, rssi, pos.accuracy, now));
    _schedule();
    notifyListeners();
  }

  void _schedule() {
    _recalc ??= Timer(const Duration(seconds: 2), () {
      _recalc = null;
      final id = target;
      if (id == null) return;
      final prior = beacons.beacons[id]?.status.txAt1m.toDouble() ?? -59;
      result = estimate(thin(current), priorP0: prior);
      notifyListeners();
    });
  }

  @override
  void dispose() {
    position.removeListener(_onPosition);
    _recalc?.cancel();
    super.dispose();
  }
}
