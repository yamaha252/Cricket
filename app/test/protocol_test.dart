import 'dart:math' as math;
import 'dart:typed_data';

import 'package:cricket/map/tiles.dart';
import 'package:cricket/protocol/cricket.dart';
import 'package:cricket/state/locator.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:latlong2/latlong.dart';

void main() {
  test('status payload v2 parses (docs/protocol.md layout)', () {
    final b = ByteData(22)
      ..setUint8(0, 2)
      ..setUint32(1, 0xDEADBEEF, Endian.little)
      ..setUint8(5, 2) // ALARM
      ..setUint8(6, 0x04 | 0x80) // position valid, pairing window
      ..setUint16(7, 3912, Endian.little)
      ..setInt8(9, -59)
      ..setUint16(10, 17, Endian.little)
      ..setInt32(12, 512345678, Endian.little)
      ..setInt32(16, 712345678, Endian.little)
      ..setUint16(20, 42, Endian.little);
    final s = CricketStatus.parse(b.buffer.asUint8List())!;
    expect(s.idHex, 'DEADBEEF');
    expect(s.mode, BeaconMode.alarm);
    expect(s.mode.isLost, isTrue);
    expect(s.flags.positionValid, isTrue);
    expect(s.flags.pairingWindow, isTrue);
    expect(s.batteryMv, 3912);
    expect(s.txAt1m, -59);
    expect(s.minutesInMode, 17);
    expect(s.lat, closeTo(51.2345678, 1e-9));
    expect(s.lon, closeTo(71.2345678, 1e-9));
    expect(s.hasPosition, isTrue);
  });

  test('wrong version or short payload is ignored', () {
    expect(CricketStatus.parse(Uint8List(22)..[0] = 1), isNull);
    expect(CricketStatus.parse(Uint8List(10)..[0] = 2), isNull);
  });

  test('position age 0xFFFF means no position', () {
    final d = Uint8List(22)
      ..[0] = 2
      ..[6] = 0x04
      ..[20] = 0xFF
      ..[21] = 0xFF;
    expect(CricketStatus.parse(d)!.hasPosition, isFalse);
  });

  test('settings TLV round trip', () {
    final s = BeaconSettings(
      name: 'Сверчок',
      txCoded: 8,
      tx1m: -4,
      rssi1m: -61,
      contact: '+7 700 000 00 00',
      preflightBeep: false,
      intervals: {BeaconMode.beacon: const Intervals(2000, 4000), BeaconMode.lowBat: const Intervals(10000, 0)},
    );
    expect(s.validate(), isNull);
    final d = BeaconSettings.decode(s.encode());
    expect(d.name, 'Сверчок');
    expect(d.tx1m, -4);
    expect(d.rssi1m, -61);
    expect(d.contact, '+7 700 000 00 00');
    expect(d.preflightBeep, isFalse);
    expect(d.intervals[BeaconMode.beacon]!.oneMMs, 4000);
    expect(d.intervals[BeaconMode.lowBat]!.codedMs, 10000);
  });

  test('settings validation mirrors firmware rules', () {
    expect(BeaconSettings(txCoded: 9).validate(), isNotNull);
    expect(BeaconSettings(intervals: {BeaconMode.alarm: const Intervals(0, 0)}).validate(), isNotNull);
    expect(BeaconSettings(intervals: {BeaconMode.alarm: const Intervals(50, 1000)}).validate(), isNotNull);
  });

  test('locator finds a beacon from a walk around it', () {
    const lat0 = 51.1, lon0 = 71.4;
    const mLon = 111320.0 * 0.6280; // cos(51.1°)
    final beacon = LatLng(lat0 + 60 / 111320.0, lon0 + 40 / mLon);
    final rnd = math.Random(1);
    final samples = <Sample>[];
    for (var i = 0; i < 60; i++) {
      // walk along a line 150 m long, then back 30 m north
      final x = -50.0 + (i % 30) * 5;
      final y = i < 30 ? 0.0 : 30.0;
      final lat = lat0 + y / 111320.0, lon = lon0 + x / mLon;
      final d = math.max(1.0, const Distance().as(LengthUnit.Meter, LatLng(lat, lon), beacon));
      final rssi = -59 - 22 * math.log(d) / math.ln10 + (rnd.nextDouble() - 0.5) * 6;
      samples.add(Sample(lat, lon, rssi, 5, DateTime.now()));
    }
    final e = estimate(samples)!;
    final err = const Distance().as(LengthUnit.Meter, e.best, beacon);
    expect(err, lessThan(25));
    expect(e.radiusM, lessThan(80));
  });

  test('long walks are thinned evenly for the fit', () {
    final t0 = DateTime(2026);
    final all = [for (var i = 0; i < 3000; i++) Sample(0, i.toDouble(), -70, 5, t0)];
    expect(thin(all.sublist(0, 600)).length, 600);
    final t = thin(all);
    expect(t.length, 600);
    expect(t.first.lon, 0);
    expect(t.last.lon, 2995);
  });

  test('tile ranges cover bounds', () {
    final r = rangesFor(LatLngBounds(const LatLng(51.0, 71.0), const LatLng(51.1, 71.1)), 10, 12);
    expect(r.length, 3);
    expect(r.first.count, greaterThan(0));
    expect(lonToTileX(0, 1), 1);
    expect(latToTileY(0.0001, 1), 0);
  });
}
