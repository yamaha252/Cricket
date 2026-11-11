import 'package:flutter/material.dart';

import '../ble/ble.dart';
import '../protocol/cricket.dart';
import 'widgets.dart';

/// Bluetooth settings of a bonded beacon (D-34, docs/protocol.md «Настройки»).
class BeaconSettingsPage extends StatefulWidget {
  const BeaconSettingsPage({super.key, required this.address, required this.title});
  final String address;
  final String title;

  @override
  State<BeaconSettingsPage> createState() => _BeaconSettingsPageState();
}

class _BeaconSettingsPageState extends State<BeaconSettingsPage> {
  BeaconSettings? _s;
  String? _error;
  bool _saving = false;
  final _name = TextEditingController();
  final _contact = TextEditingController();
  final Map<BeaconMode, (TextEditingController, TextEditingController)> _iv = {};

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    Ble.instance.disconnect();
    _name.dispose();
    _contact.dispose();
    for (final (c, o) in _iv.values) {
      c.dispose();
      o.dispose();
    }
    super.dispose();
  }

  Future<void> _load() async {
    setState(() => _error = null);
    try {
      await Ble.instance.connect(widget.address);
      final s = BeaconSettings.decode(await Ble.instance.read(settingsUuid));
      if (!mounted) return;
      _name.text = s.name;
      _contact.text = s.contact;
      for (final m in intervalModes) {
        final v = s.intervals[m];
        final (c, o) = _iv[m] ??= (TextEditingController(), TextEditingController());
        c.text = '${v?.codedMs ?? ''}';
        o.text = '${v?.oneMMs ?? ''}';
      }
      setState(() => _s = s);
    } on BleException catch (e) {
      if (!mounted) return;
      // 5, 8, 15: insufficient authentication, authorization, encryption.
      setState(() => _error = const [5, 8, 15].contains(e.status)
          ? 'Нет доступа: телефон не привязан к маячку'
          : e.message);
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  Future<void> _save() async {
    final s = _s!;
    s.name = _name.text.trim();
    s.contact = _contact.text.trim();
    for (final m in intervalModes) {
      final (c, o) = _iv[m]!;
      final ct = c.text.trim(), ot = o.text.trim();
      if (ct.isEmpty && ot.isEmpty && s.intervals[m] == null) continue;
      final cv = int.tryParse(ct), ov = int.tryParse(ot);
      if (cv == null || ov == null) {
        // Do not report "saved" while silently keeping the old value.
        showSnack(context, '${m.label}: интервалы должны быть целыми числами, мс');
        return;
      }
      s.intervals[m] = Intervals(cv, ov);
    }
    final err = s.validate();
    if (err != null) {
      showSnack(context, err);
      return;
    }
    setState(() => _saving = true);
    try {
      final st = await Ble.instance.write(settingsUuid, s.encode());
      if (mounted) showSnack(context, st == 0 ? 'Сохранено' : 'Не сохранено: ${gattStatusText(st)}');
    } catch (e) {
      if (mounted) showSnack(context, '$e');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = _s;
    return Scaffold(
      appBar: AppBar(
        title: Text('Настройки: ${widget.title}'),
        actions: [
          if (s != null)
            IconButton(onPressed: _saving ? null : _save, icon: const Icon(Icons.save), tooltip: 'Сохранить'),
        ],
      ),
      body: _error != null
          ? Center(
              child: Column(mainAxisSize: MainAxisSize.min, children: [
              Padding(padding: const EdgeInsets.all(16), child: Text(_error!, textAlign: TextAlign.center)),
              FilledButton(onPressed: _load, child: const Text('Повторить')),
            ]))
          : s == null
              ? const Center(child: CircularProgressIndicator())
              : ListView(padding: const EdgeInsets.all(16), children: [
                  if (_saving) const LinearProgressIndicator(),
                  TextField(controller: _name, maxLength: 20, decoration: const InputDecoration(labelText: 'Имя устройства')),
                  TextField(
                    controller: _contact,
                    maxLength: 64,
                    decoration: const InputDecoration(
                        labelText: 'Контакт для нашедшего',
                        helperText: 'Виден всем, пока маячок потерян'),
                  ),
                  _slider('Мощность Coded, дБм', s.txCoded, -40, 8, (v) => s.txCoded = v),
                  _slider('Мощность 1M, дБм', s.tx1m, -40, 8, (v) => s.tx1m = v),
                  _slider('RSSI на 1 м, дБм', s.rssi1m, -100, 0, (v) => s.rssi1m = v),
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    title: const Text('Предполётный писк при подаче 5 В'),
                    value: s.preflightBeep,
                    onChanged: (v) => setState(() => s.preflightBeep = v),
                  ),
                  const SizedBox(height: 8),
                  Text('Интервалы рекламы, мс (0 — набор выключен, 100…10240)',
                      style: Theme.of(context).textTheme.titleSmall),
                  for (final m in intervalModes)
                    Row(children: [
                      SizedBox(width: 130, child: Text(m.label)),
                      Expanded(child: _num(_iv[m]!.$1, 'Coded')),
                      const SizedBox(width: 8),
                      Expanded(child: _num(_iv[m]!.$2, '1M')),
                    ]),
                  const SizedBox(height: 16),
                  FilledButton(onPressed: _saving ? null : _save, child: const Text('Сохранить')),
                ]),
    );
  }

  Widget _num(TextEditingController c, String label) => TextField(
        controller: c,
        keyboardType: TextInputType.number,
        decoration: InputDecoration(labelText: label, isDense: true),
      );

  Widget _slider(String label, int value, int min, int max, ValueChanged<int> set) =>
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('$label: $value'),
        Slider(
          value: value.toDouble().clamp(min.toDouble(), max.toDouble()),
          min: min.toDouble(),
          max: max.toDouble(),
          divisions: max - min,
          label: '$value',
          onChanged: (v) => setState(() => set(v.round())),
        ),
      ]);
}
