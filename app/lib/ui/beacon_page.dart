import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:latlong2/latlong.dart';

import '../app.dart';
import '../ble/ble.dart';
import '../protocol/cricket.dart';
import '../state/beacons.dart';
import 'beacon_settings_page.dart';
import 'beacons_page.dart';
import 'widgets.dart';

class BeaconPage extends StatefulWidget {
  const BeaconPage({super.key, required this.id});
  final int id;

  @override
  State<BeaconPage> createState() => _BeaconPageState();
}

class _BeaconPageState extends State<BeaconPage> {
  bool _sound = false;
  Timer? _beepTimer;
  DateTime _lastBeep = DateTime.fromMillisecondsSinceEpoch(0);
  bool _busy = false;
  String? _connected; // address of the open GATT link
  String? _contact;

  @override
  void initState() {
    super.initState();
    Ble.instance.keepScreenOn(true);
    _beepTimer = Timer.periodic(const Duration(milliseconds: 50), (_) => _tick());
  }

  @override
  void dispose() {
    _beepTimer?.cancel();
    Ble.instance.keepScreenOn(false);
    if (_connected != null) Ble.instance.disconnect();
    super.dispose();
  }

  /// Metal-detector sound: the stronger the signal, the faster the beeps.
  void _tick() {
    if (!_sound || !mounted) return;
    final r = Services.of(context).beacons.beacons[widget.id];
    if (r == null || r.age > const Duration(seconds: 4) || r.smoothRssi == null) return;
    final f = rssiFraction(r.smoothRssi!);
    final period = Duration(milliseconds: (1500 - 1400 * f).round());
    if (DateTime.now().difference(_lastBeep) >= period) {
      _lastBeep = DateTime.now();
      Ble.instance.beep(40);
    }
  }

  // ---------------------------------------------------------------- GATT actions

  Future<void> _withLink(Future<void> Function() action) async {
    final r = Services.of(context).beacons.beacons[widget.id];
    if (r == null) return;
    setState(() => _busy = true);
    try {
      if (_connected != r.address) {
        await Ble.instance.connect(r.address);
        _connected = r.address;
        Ble.instance.connStream
            .firstWhere((e) => e['event'] == 'state' && e['state'] == 'disconnected')
            .then((_) => _connected = null);
      }
      await action();
    } on TimeoutException {
      if (mounted) showSnack(context, 'Маячок не ответил вовремя');
    } on PlatformException catch (e) {
      if (mounted) showSnack(context, e.message ?? e.code);
    } on BleException catch (e) {
      _connected = null;
      if (mounted) showSnack(context, '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _command(Uint8List cmd, String done) => _withLink(() async {
        final st = await Ble.instance.write(controlUuid, cmd);
        if (!mounted) return;
        if (st == 0) {
          showSnack(context, done);
        } else if (st == 5 || st == 15) {
          showSnack(context, 'Команда только для привязанного телефона');
        } else {
          showSnack(context, 'Ошибка: ${gattStatusText(st)}');
        }
      });

  Future<void> _readContact() => _withLink(() async {
        final v = await Ble.instance.read(ownerUuid);
        if (!mounted) return;
        setState(() => _contact = v.isEmpty ? '' : utf8.decode(v, allowMalformed: true));
      });

  Future<void> _pair() async {
    final store = Services.of(context).beacons;
    final r = store.beacons[widget.id];
    if (r == null) return;
    await _withLink(() async {
      if (await Ble.instance.bondState(r.address) != 'bonded') {
        final bonded = Ble.instance.connStream
            .where((e) => e['event'] == 'bond' && e['address'] == r.address)
            .firstWhere((e) => e['bond'] != 'bonding')
            .timeout(const Duration(seconds: 40));
        bonded.ignore(); // errors are handled by the await below
        if (!await Ble.instance.createBond(r.address)) {
          throw BleException('Телефон не начал привязку');
        }
        final e = await bonded;
        if (e['bond'] != 'bonded') throw BleException('Привязка отклонена: окно привязки закрыто?');
      }
      if (!mounted) return;
      final label = await _askLabel(store.labelOf(widget.id));
      // Cancelled or left empty: keep the current name, never a blank one.
      store.setMine(
          widget.id, label == null || label.isEmpty ? store.labelOf(widget.id) : label);
      if (mounted) showSnack(context, 'Маячок привязан');
    });
  }

  Future<String?> _askLabel(String initial) {
    final c = TextEditingController(text: initial);
    return showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Название маячка'),
        content: TextField(controller: c, autofocus: true),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Отмена')),
          FilledButton(onPressed: () => Navigator.pop(ctx, c.text.trim()), child: const Text('OK')),
        ],
      ),
    );
  }

  Future<bool> _confirm(String text) async =>
      await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          content: Text(text),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Отмена')),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Да')),
          ],
        ),
      ) ??
      false;

  // ---------------------------------------------------------------- UI

  @override
  Widget build(BuildContext context) {
    final services = Services.of(context);
    final store = services.beacons;
    return ListenableBuilder(
      listenable: Listenable.merge([store, services.locator]),
      builder: (context, _) {
        final r = store.beacons[widget.id];
        if (r == null) {
          return Scaffold(appBar: AppBar(), body: const Center(child: Text('Маячок не слышен')));
        }
        final mine = store.mine.containsKey(r.id);
        final s = r.status;
        return Scaffold(
          appBar: AppBar(
            title: Text(store.labelOf(r.id)),
            actions: [
              if (mine)
                IconButton(
                  tooltip: 'Переименовать',
                  icon: const Icon(Icons.edit),
                  onPressed: () async {
                    final l = await _askLabel(store.labelOf(r.id));
                    if (l != null && l.isNotEmpty) store.setMine(r.id, l);
                  },
                ),
            ],
          ),
          body: ListView(
            padding: const EdgeInsets.all(12),
            children: [
              if (_busy) const LinearProgressIndicator(),
              _HotCold(record: r, sound: _sound, onSound: (v) => setState(() => _sound = v)),
              _trackCard(services, r),
              _infoCard(services, r),
              if (s.mode.isLost && !mine) _foundCard(r),
              _actionsCard(r, mine),
            ],
          ),
        );
      },
    );
  }

  Widget _trackCard(Services services, BeaconRecord r) {
    final loc = services.locator;
    final active = loc.target == r.id && loc.recording;
    final n = loc.samples[r.id]?.length ?? 0;
    return Card(
      child: Column(children: [
        SwitchListTile(
          title: const Text('Пеленг: записывать сигнал и GPS'),
          subtitle: Text(n == 0
              ? 'Ходите вокруг: приложение построит область, где лежит маячок'
              : 'Точек: $n${loc.target == r.id && loc.result != null ? ', оценка ±${loc.result!.radiusM.round()} м' : ''}'),
          value: active,
          onChanged: (v) {
            loc.select(r.id);
            loc.setRecording(v);
          },
        ),
        OverflowBar(alignment: MainAxisAlignment.end, children: [
          if (n > 0) TextButton(onPressed: () => loc..select(r.id)..clear(), child: const Text('Сбросить')),
          TextButton(
            onPressed: () {
              loc.select(r.id);
              Navigator.of(context).pop();
              services.showMap(focus: loc.result?.best ?? (r.status.hasPosition ? LatLng(r.status.lat, r.status.lon) : null));
            },
            child: const Text('На карте'),
          ),
        ]),
      ]),
    );
  }

  Widget _infoCard(Services services, BeaconRecord r) {
    final s = r.status;
    final rows = <(String, String)>[
      ('ID', s.idHex),
      ('Режим', '${s.mode.label}, ${modeDuration(s)}'),
      ('Батарея', '${(s.batteryMv / 1000).toStringAsFixed(2)} В'),
      ('Радио', '${phyLabel(r)} · пакетов Coded ${r.codedPackets}, 1M ${r.oneMPackets}'),
      ('RSSI на 1 м', '${s.txAt1m} дБм'),
      ('Флаги', s.flags.describe().isEmpty ? '—' : s.flags.describe().join(', ')),
      ('Последний пакет', '${formatAge(r.age)} назад'),
      if (s.hasPosition)
        ('GPS полётника', '${s.lat.toStringAsFixed(6)}, ${s.lon.toStringAsFixed(6)}, ${formatAge(Duration(seconds: s.positionAgeS))} назад'),
    ];
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(children: [
          for (final (k, v) in rows)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 2),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                SizedBox(width: 130, child: Text(k, style: Theme.of(context).textTheme.bodySmall)),
                Expanded(child: Text(v)),
              ]),
            ),
          if (s.hasPosition)
            Align(
              alignment: Alignment.centerRight,
              child: TextButton.icon(
                icon: const Icon(Icons.place),
                label: const Text('Координаты на карте'),
                onPressed: () {
                  services.locator.select(r.id);
                  Navigator.of(context).pop();
                  services.showMap(focus: LatLng(s.lat, s.lon));
                },
              ),
            ),
        ]),
      ),
    );
  }

  Widget _foundCard(BeaconRecord r) => Card(
        color: Theme.of(context).colorScheme.tertiaryContainer,
        child: ListTile(
          leading: const Icon(Icons.contact_phone),
          title: const Text('Чужой потерянный маячок'),
          subtitle: Text(_contact == null
              ? 'Прочитайте контакт владельца'
              : (_contact!.isEmpty ? 'Владелец не оставил контакт' : _contact!)),
          trailing: TextButton(onPressed: _busy ? null : _readContact, child: const Text('Контакт')),
        ),
      );

  Widget _actionsCard(BeaconRecord r, bool mine) {
    final store = Services.of(context).beacons;
    final s = r.status;
    final pairingOpen = s.flags.pairingWindow;
    final b = _busy;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Пищать и мигать', style: Theme.of(context).textTheme.titleSmall),
          Wrap(spacing: 8, children: [
            for (final sec in [10, 30, 60])
              FilledButton.tonal(
                  onPressed: b ? null : () => _command(Command.find(sec), 'Пищит $sec с'), child: Text('$sec с')),
            OutlinedButton(onPressed: b ? null : () => _command(Command.find(0), 'Писк остановлен'), child: const Text('Стоп')),
          ]),
          const Divider(),
          Wrap(spacing: 8, runSpacing: 4, children: [
            if (mine && s.mode.isLost)
              FilledButton(
                  onPressed: b ? null : () => _command(Command.silence(), 'Тревога выключена'),
                  child: const Text('Выключить тревогу')),
            if (!mine || pairingOpen)
              FilledButton.tonalIcon(
                icon: const Icon(Icons.link),
                onPressed: b ? null : _pair,
                label: Text(pairingOpen ? 'Привязать (окно открыто)' : 'Привязать'),
              ),
            if (mine)
              OutlinedButton.icon(
                icon: const Icon(Icons.tune),
                label: const Text('Настройки маячка'),
                onPressed: b
                    ? null
                    : () async {
                        // The settings page opens its own link.
                        if (_connected != null) {
                          await Ble.instance.disconnect();
                          _connected = null;
                        }
                        if (!mounted) return;
                        Navigator.of(context).push(MaterialPageRoute(
                            builder: (_) => BeaconSettingsPage(address: r.address, title: store.labelOf(r.id))));
                      },
              ),
            if (mine) OutlinedButton(onPressed: b ? null : _readContact, child: const Text('Контакт')),
          ]),
          if (mine && _contact != null) Padding(padding: const EdgeInsets.only(top: 4), child: Text('Контакт: ${_contact!.isEmpty ? '—' : _contact}')),
          if (mine) ...[
            const Divider(),
            Text('Обслуживание', style: Theme.of(context).textTheme.titleSmall),
            Wrap(spacing: 8, children: [
              TextButton(
                  onPressed: b ? null : () => _command(Command.dfu(), 'Окно обновления открыто на 5 мин'),
                  child: const Text('Окно DFU')),
              TextButton(
                onPressed: b
                    ? null
                    : () async {
                        if (await _confirm('Маячок забудет все телефоны, кроме этого. Продолжить?')) {
                          _command(Command.forget(), 'Остальные телефоны забыты');
                        }
                      },
                child: const Text('Забыть другие телефоны'),
              ),
              TextButton(
                onPressed: b
                    ? null
                    : () async {
                        if (await _confirm('Вернуть настройки Bluetooth по умолчанию?')) {
                          _command(Command.defaults(), 'Настройки сброшены');
                        }
                      },
                child: const Text('Настройки по умолчанию'),
              ),
              TextButton(
                onPressed: () async {
                  if (await _confirm('Убрать маячок из своих? Привязка в телефоне останется.')) {
                    store.setMine(r.id, null);
                  }
                },
                child: const Text('Убрать из своих'),
              ),
            ]),
          ],
        ]),
      ),
    );
  }
}

class _HotCold extends StatelessWidget {
  const _HotCold({required this.record, required this.sound, required this.onSound});
  final BeaconRecord record;
  final bool sound;
  final ValueChanged<bool> onSound;

  @override
  Widget build(BuildContext context) {
    final heard = record.age < const Duration(seconds: 4) && record.smoothRssi != null;
    final rssi = record.smoothRssi;
    final f = heard ? rssiFraction(rssi!) : 0.0;
    final now = record.medianRssi(const Duration(seconds: 2));
    final before = _medianBetween(record, 6, 3);
    String trend = '';
    if (heard && now != null && before != null) {
      final d = now - before;
      trend = d > 2 ? 'теплее ▲' : (d < -2 ? 'холоднее ▼' : 'так же');
    }
    final color = heard ? heatColor(f) : Colors.grey;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(children: [
          SizedBox(
            width: 200,
            height: 200,
            child: Stack(alignment: Alignment.center, children: [
              SizedBox.expand(
                child: CircularProgressIndicator(
                  value: f,
                  strokeWidth: 18,
                  color: color,
                  backgroundColor: Theme.of(context).colorScheme.surfaceContainerHighest,
                ),
              ),
              Column(mainAxisSize: MainAxisSize.min, children: [
                Text(heard ? '${rssi!.round()}' : '—',
                    style: Theme.of(context).textTheme.displayMedium?.copyWith(color: color)),
                const Text('дБм'),
                if (heard && record.distanceM != null) Text('≈ ${formatDistance(record.distanceM!)}'),
              ]),
            ]),
          ),
          const SizedBox(height: 8),
          Text(heard ? trend : 'нет сигнала ${formatAge(record.age)}',
              style: Theme.of(context).textTheme.titleMedium),
          SwitchListTile(
            title: const Text('Звук как у металлоискателя'),
            value: sound,
            onChanged: onSound,
          ),
        ]),
      ),
    );
  }

  double? _medianBetween(BeaconRecord r, int fromS, int toS) {
    final now = DateTime.now();
    final v = r.history
        .where((p) =>
            p.time.isAfter(now.subtract(Duration(seconds: fromS))) &&
            p.time.isBefore(now.subtract(Duration(seconds: toS))))
        .map((p) => p.rssi)
        .toList()
      ..sort();
    return v.isEmpty ? null : v[v.length ~/ 2].toDouble();
  }
}
