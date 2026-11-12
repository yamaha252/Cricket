import 'package:flutter/material.dart';

import '../app.dart';
import '../ble/ble.dart';
import '../protocol/cricket.dart';
import '../state/beacons.dart';
import 'beacon_page.dart';
import 'widgets.dart';

class BeaconsPage extends StatelessWidget {
  const BeaconsPage({super.key});

  @override
  Widget build(BuildContext context) {
    final store = Services.of(context).beacons;
    return Scaffold(
      appBar: AppBar(title: const Text('Маячки Cricket')),
      body: ListenableBuilder(
        listenable: store,
        builder: (context, _) {
          final list = store.sorted;
          return ListView(
            children: [
              _ScanBanner(store: store),
              if (list.isEmpty && store.state == ScanState.scanning)
                Padding(
                  padding: const EdgeInsets.all(32),
                  child: Center(
                      child: Text(store.adapter?.ios == true ? 'Ищу маячки…' : 'Ищу маячки…\nCoded PHY и 1M',
                          textAlign: TextAlign.center)),
                ),
              for (final r in list) _BeaconTile(record: r, mine: store.mine.containsKey(r.id)),
            ],
          );
        },
      ),
    );
  }
}

class _ScanBanner extends StatelessWidget {
  const _ScanBanner({required this.store});
  final BeaconStore store;

  @override
  Widget build(BuildContext context) {
    final a = store.adapter;
    switch (store.state) {
      case ScanState.noPermission:
        return _banner(context, Icons.lock_outline, 'Нужны разрешения Bluetooth и геолокации',
            action: TextButton(
                onPressed: () async {
                  await store.start();
                  if (store.state == ScanState.noPermission) await Ble.instance.openAppSettings();
                },
                child: const Text('Разрешить')));
      case ScanState.bluetoothOff:
        return _banner(context, Icons.bluetooth_disabled, 'Bluetooth выключен',
            // iOS has no "turn on" dialog: the button opens the app's settings.
            action: TextButton(
                onPressed: () => Ble.instance.requestEnable(),
                child: Text(a?.ios == true ? 'Настройки' : 'Включить')));
      case ScanState.unsupported:
        return _banner(context, Icons.error_outline, 'Bluetooth недоступен ${store.error ?? ''}');
      case ScanState.failed:
        return _banner(context, Icons.error_outline, 'Сканирование не запустилось: ${store.error ?? ''}',
            action: TextButton(onPressed: store.start, child: const Text('Повторить')));
      case ScanState.idle:
        return _banner(context, Icons.pause, 'Сканирование остановлено',
            action: TextButton(onPressed: store.start, child: const Text('Старт')));
      case ScanState.scanning:
        final coded = a?.ios == true
            ? 'iPhone принимает только 1M'
            : store.codedTotal > 0
                ? 'Coded PHY принимается'
                : (a?.codedSupported == true ? 'Coded заявлен, пакетов ещё не было' : 'Coded не заявлен телефоном');
        return Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
          child: Row(children: [
            const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2)),
            const SizedBox(width: 12),
            Expanded(
              child: Text('$coded · пакетов Coded ${store.codedTotal}, 1M ${store.oneMTotal}',
                  style: Theme.of(context).textTheme.bodySmall),
            ),
          ]),
        );
    }
  }

  Widget _banner(BuildContext context, IconData icon, String text, {Widget? action}) => Card(
        margin: const EdgeInsets.all(12),
        color: Theme.of(context).colorScheme.errorContainer,
        child: ListTile(leading: Icon(icon), title: Text(text), trailing: action),
      );
}

class _BeaconTile extends StatelessWidget {
  const _BeaconTile({required this.record, required this.mine});
  final BeaconRecord record;
  final bool mine;

  @override
  Widget build(BuildContext context) {
    final s = record.status;
    final store = Services.of(context).beacons;
    final lost = s.mode.isLost;
    final scheme = Theme.of(context).colorScheme;
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      color: lost ? scheme.errorContainer : null,
      child: ListTile(
        onTap: () => Navigator.of(context)
            .push(MaterialPageRoute(builder: (_) => BeaconPage(id: record.id))),
        leading: SignalBars(rssi: record.fresh ? record.smoothRssi : null),
        title: Row(children: [
          Flexible(child: Text(store.labelOf(record.id), overflow: TextOverflow.ellipsis)),
          const SizedBox(width: 8),
          if (mine) const Icon(Icons.star, size: 16) else const Text('чужой', style: TextStyle(fontSize: 12)),
        ]),
        subtitle: Text([
          s.mode.label,
          '${(s.batteryMv / 1000).toStringAsFixed(2)} В',
          if (record.smoothRssi != null) '${record.smoothRssi!.round()} дБм',
          if (record.distanceM != null) '≈${formatDistance(record.distanceM!)}',
          phyLabel(record),
          if (!record.fresh) 'был ${formatAge(record.age)} назад',
          ...s.flags.describe(),
        ].join(' · ')),
        trailing: s.hasPosition ? const Icon(Icons.gps_fixed) : null,
      ),
    );
  }
}

String phyLabel(BeaconRecord r) => [
      if (r.codedPackets > 0) 'Coded',
      if (r.oneMPackets > 0) '1M',
    ].join('+');

String formatDistance(double m) => m < 1000 ? '${m.round()} м' : '${(m / 1000).toStringAsFixed(1)} км';

String formatAge(Duration d) {
  if (d.inSeconds < 60) return '${d.inSeconds} с';
  if (d.inMinutes < 60) return '${d.inMinutes} мин';
  if (d.inHours < 48) return '${d.inHours} ч';
  return '${d.inDays} дн';
}

String modeDuration(CricketStatus s) =>
    s.minutesInMode >= 65535 ? '> 45 дн' : formatAge(Duration(minutes: s.minutesInMode));
