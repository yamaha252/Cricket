// Cricket protocol v2: advertising payload, GATT UUIDs, commands, settings TLV.
// Source of truth: docs/protocol.md. All multi-byte numbers are little-endian.

import 'dart:convert';
import 'dart:math' as math;
import 'dart:typed_data';

const int cricketCompanyId = 0xFFFF;
const int cricketProtocolVersion = 2;

const String serviceUuid = '2083eb8d-7651-438b-b7fb-75aff5da9c00';
const String statusUuid = '2083eb8d-7651-438b-b7fb-75aff5da9c01';
const String controlUuid = '2083eb8d-7651-438b-b7fb-75aff5da9c02';
const String settingsUuid = '2083eb8d-7651-438b-b7fb-75aff5da9c03';
const String ownerUuid = '2083eb8d-7651-438b-b7fb-75aff5da9c04';

enum BeaconMode {
  onDrone('На дроне'),
  escalate('Тревога растёт'),
  alarm('Тревога'),
  beacon('Маяк'),
  standby('Ожидание'),
  lowBat('Батарея садится'),
  ship('Хранение'),
  unknown('?');

  const BeaconMode(this.label);
  final String label;

  static BeaconMode fromByte(int b) =>
      b < BeaconMode.values.length - 1 ? BeaconMode.values[b] : BeaconMode.unknown;

  /// Modes in which the beacon is considered lost: FIND is accepted from anyone
  /// (≤ 60 s) and the owner contact is readable.
  bool get isLost =>
      this == BeaconMode.escalate || this == BeaconMode.alarm || this == BeaconMode.beacon;
}

class BeaconFlags {
  const BeaconFlags(this.raw);
  final int raw;
  bool _bit(int n) => raw & (1 << n) != 0;
  bool get power5v => _bit(0);
  bool get charging => _bit(1);
  bool get positionValid => _bit(2);
  bool get beeping => _bit(3);
  bool get armedBeforeLoss => _bit(4);
  bool get impact => _bit(5);
  bool get dfuWindow => _bit(6);
  bool get pairingWindow => _bit(7);

  List<String> describe() => [
        if (power5v) '5 В',
        if (charging) 'заряд',
        if (positionValid) 'GPS',
        if (beeping) 'пищит',
        if (armedBeforeLoss) 'был armed',
        if (impact) 'удар',
        if (dfuWindow) 'окно DFU',
        if (pairingWindow) 'окно привязки',
      ];
}

/// The 22 bytes after the Company ID: advertising payload and the status
/// characteristic share the same layout.
class CricketStatus {
  CricketStatus({
    required this.id,
    required this.mode,
    required this.flags,
    required this.batteryMv,
    required this.txAt1m,
    required this.minutesInMode,
    required this.latE7,
    required this.lonE7,
    required this.positionAgeS,
  });

  final int id;
  final BeaconMode mode;
  final BeaconFlags flags;
  final int batteryMv;
  final int txAt1m;
  final int minutesInMode;
  final int latE7;
  final int lonE7;
  final int positionAgeS;

  static const int length = 22;

  /// Parses data that starts with the version byte. Returns null for other
  /// versions or wrong length.
  static CricketStatus? parse(Uint8List d) {
    if (d.length < length || d[0] != cricketProtocolVersion) return null;
    final b = ByteData.sublistView(d);
    return CricketStatus(
      id: b.getUint32(1, Endian.little),
      mode: BeaconMode.fromByte(d[5]),
      flags: BeaconFlags(d[6]),
      batteryMv: b.getUint16(7, Endian.little),
      txAt1m: b.getInt8(9),
      minutesInMode: b.getUint16(10, Endian.little),
      latE7: b.getInt32(12, Endian.little),
      lonE7: b.getInt32(16, Endian.little),
      positionAgeS: b.getUint16(20, Endian.little),
    );
  }

  bool get hasPosition => flags.positionValid && positionAgeS != 0xFFFF;
  double get lat => latE7 / 1e7;
  double get lon => lonE7 / 1e7;
  String get idHex => formatId(id);
}

String formatId(int id) => id.toRadixString(16).toUpperCase().padLeft(8, '0');

/// Distance from RSSI by the log-distance model; [n] is the path-loss exponent
/// (2 in free space, 2–3 over ground and grass).
double rssiToMeters(double rssi, int txAt1m, {double n = 2.2}) =>
    math.pow(10, (txAt1m - rssi) / (10 * n)).toDouble();

// ---------------------------------------------------------------- commands

class Command {
  static Uint8List find(int seconds) => Uint8List.fromList([0x01, seconds.clamp(0, 255)]);
  static Uint8List silence() => Uint8List.fromList([0x02]);
  static Uint8List dfu() => Uint8List.fromList([0x03]);
  static Uint8List forget() => Uint8List.fromList([0x04]);
  static Uint8List defaults() => Uint8List.fromList([0x05]);
}

// ---------------------------------------------------------------- settings TLV

class SettingsKey {
  static const name = 0x01;
  static const txCoded = 0x02;
  static const tx1m = 0x03;
  static const rssi1m = 0x04;
  static const contact = 0x05;
  static const preflightBeep = 0x06;
  static const intervalBase = 0x10; // + mode 0..5
}

/// Modes that have interval settings (keys 0x10…0x15).
const intervalModes = [
  BeaconMode.onDrone,
  BeaconMode.escalate,
  BeaconMode.alarm,
  BeaconMode.beacon,
  BeaconMode.standby,
  BeaconMode.lowBat,
];

class Intervals {
  const Intervals(this.codedMs, this.oneMMs);
  final int codedMs;
  final int oneMMs;
}

class BeaconSettings {
  BeaconSettings({
    this.name = 'Cricket',
    this.txCoded = 8,
    this.tx1m = 8,
    this.rssi1m = -59,
    this.contact = '',
    this.preflightBeep = true,
    Map<BeaconMode, Intervals>? intervals,
  }) : intervals = intervals ?? {};

  String name;
  int txCoded;
  int tx1m;
  int rssi1m;
  String contact;
  bool preflightBeep;
  Map<BeaconMode, Intervals> intervals;

  static BeaconSettings decode(Uint8List d) {
    final s = BeaconSettings();
    var i = 0;
    while (i + 2 <= d.length) {
      final key = d[i], len = d[i + 1];
      if (i + 2 + len > d.length) break;
      final v = Uint8List.sublistView(d, i + 2, i + 2 + len);
      final b = ByteData.sublistView(v);
      switch (key) {
        case SettingsKey.name:
          s.name = utf8.decode(v, allowMalformed: true);
        case SettingsKey.txCoded when len == 1:
          s.txCoded = b.getInt8(0);
        case SettingsKey.tx1m when len == 1:
          s.tx1m = b.getInt8(0);
        case SettingsKey.rssi1m when len == 1:
          s.rssi1m = b.getInt8(0);
        case SettingsKey.contact:
          s.contact = utf8.decode(v, allowMalformed: true);
        case SettingsKey.preflightBeep when len == 1:
          s.preflightBeep = v[0] != 0;
        default:
          final m = key - SettingsKey.intervalBase;
          if (m >= 0 && m < intervalModes.length && len == 4) {
            s.intervals[intervalModes[m]] =
                Intervals(b.getUint16(0, Endian.little), b.getUint16(2, Endian.little));
          }
      }
      i += 2 + len;
    }
    return s;
  }

  /// Encodes all settings; the beacon applies them atomically.
  Uint8List encode() {
    final out = BytesBuilder();
    void rec(int key, List<int> v) {
      out.addByte(key);
      out.addByte(v.length);
      out.add(v);
    }

    int s8(int x) => x & 0xFF;
    final nameBytes = utf8.encode(name);
    rec(SettingsKey.name, nameBytes.take(20).toList());
    rec(SettingsKey.txCoded, [s8(txCoded)]);
    rec(SettingsKey.tx1m, [s8(tx1m)]);
    rec(SettingsKey.rssi1m, [s8(rssi1m)]);
    rec(SettingsKey.contact, utf8.encode(contact).take(64).toList());
    rec(SettingsKey.preflightBeep, [preflightBeep ? 1 : 0]);
    for (var m = 0; m < intervalModes.length; m++) {
      final iv = intervals[intervalModes[m]];
      if (iv == null) continue;
      final b = ByteData(4)
        ..setUint16(0, iv.codedMs, Endian.little)
        ..setUint16(2, iv.oneMMs, Endian.little);
      rec(SettingsKey.intervalBase + m, b.buffer.asUint8List());
    }
    return out.toBytes();
  }

  /// Local check mirroring the firmware rules, so the user sees the reason
  /// instead of a bare ATT error. Returns null if valid.
  String? validate() {
    if (utf8.encode(name).isEmpty || utf8.encode(name).length > 20) return 'Имя: от 1 до 20 байт (русская буква занимает 2)';
    if (utf8.encode(contact).length > 64) return 'Контакт: до 64 байт (русская буква занимает 2)';
    for (final p in [txCoded, tx1m]) {
      if (p < -40 || p > 8) return 'Мощность: −40…+8 дБм';
    }
    if (rssi1m > 0) return 'RSSI на 1 м должен быть ≤ 0';
    for (final e in intervals.entries) {
      bool ok(int ms) => ms == 0 || (ms >= 100 && ms <= 10240);
      if (!ok(e.value.codedMs) || !ok(e.value.oneMMs)) {
        return '${e.key.label}: интервал 0 или 100…10240 мс';
      }
      if (e.value.codedMs == 0 && e.value.oneMMs == 0) {
        return '${e.key.label}: хотя бы один набор должен работать';
      }
    }
    return null;
  }
}

/// iOS still holds pairing keys the beacon has erased (FORGET from another
/// phone, a fifth phone pushed this one out): only the user can drop them.
const forgottenStatus = 0x20E;
const forgottenText = 'маячок забыл этот телефон: в настройках Bluetooth iPhone '
    'выберите «Забыть это устройство» и привяжите заново';

/// Human-readable meaning of a GATT status returned by a read or a write.
String gattStatusText(int status) => switch (status) {
      0 => 'OK',
      5 || 15 => 'нужна привязка (шифрование)',
      6 => 'неизвестный ключ или команда',
      13 => 'неверная длина',
      0xFF => 'значение вне допустимого',
      133 => 'ошибка GATT (133)',
      // iOS, CoreBluetooth errors passed as 0x200 + CBError code.
      0x20E => forgottenText,
      0x20F => 'шифрование не установилось, повторите',
      0x206 || 0x207 => 'связь с маячком потеряна',
      _ => 'ошибка $status',
    };
