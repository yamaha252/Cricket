import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../app.dart';
import '../map/tiles.dart';
import 'widgets.dart';

/// Download limit per area: keeps one request within reason for the
/// volunteer-run OpenTopoMap servers.
const int maxTilesPerDownload = 30000;

class OfflineMapsPage extends StatefulWidget {
  const OfflineMapsPage({super.key});
  @override
  State<OfflineMapsPage> createState() => _OfflineMapsPageState();
}

class _OfflineMapsPageState extends State<OfflineMapsPage> {
  AreaDownload? _job;
  RangeValues _zooms = const RangeValues(10, 16);
  final Map<String, (int, int)> _sizes = {};

  ValueNotifier<int>? _tab;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _tab?.removeListener(_onTab);
    _tab = Services.of(context).tab..addListener(_onTab);
    _refreshSizes();
  }

  @override
  void dispose() {
    _tab?.removeListener(_onTab);
    super.dispose();
  }

  void _onTab() {
    if (_tab?.value == 2) _refreshSizes();
  }

  Future<void> _refreshSizes() async {
    for (final s in TileStore.instance.sources) {
      _sizes[s.id] = await TileStore.instance.cacheSize(s);
    }
    if (mounted) setState(() {});
  }

  Future<void> _download(MapState map) async {
    final b = map.visible.value;
    if (b == null) {
      showSnack(context, 'Откройте карту и выберите область');
      return;
    }
    final src = map.source.bulkDownload ? map.source : openTopoMap;
    final ranges = rangesFor(b, _zooms.start.round(), _zooms.end.round().clamp(0, src.maxZoom));
    final job = AreaDownload(src, ranges);
    if (job.total > maxTilesPerDownload) {
      showSnack(context, 'Слишком много тайлов (${job.total}). Уменьшите область или максимальный масштаб.');
      return;
    }
    setState(() => _job = job);
    job.addListener(() {
      if (mounted) setState(() {});
    });
    await job.run();
    await _refreshSizes();
    if (mounted) {
      showSnack(
          context,
          job.aborted
              ? 'Загрузка прервана: нет сети или сервер не отвечает'
              : job.cancelled
                  ? 'Загрузка остановлена'
                  : 'Готово: ${job.done - job.failed} тайлов, ошибок ${job.failed}');
    }
  }

  Future<void> _import() async {
    final f = await FilePicker.pickFile(dialogTitle: 'Файл .mbtiles');
    if (f?.path == null) return;
    try {
      final s = await TileStore.instance.importMbtiles(f!.path!);
      await _refreshSizes();
      if (mounted) showSnack(context, 'Добавлена карта «${s.name}»');
    } catch (e) {
      if (mounted) showSnack(context, 'Не удалось открыть: $e');
    } finally {
      // The picker leaves its own copy of the (large) file in the cache.
      FilePicker.clearTemporaryFiles().catchError((_) {});
    }
  }

  Future<bool> _confirm(String text) async =>
      await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          content: Text(text),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Отмена')),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Удалить')),
          ],
        ),
      ) ??
      false;

  @override
  Widget build(BuildContext context) {
    final map = Services.of(context).map;
    return Scaffold(
      appBar: AppBar(title: const Text('Офлайн-карты')),
      body: ListenableBuilder(
        listenable: Listenable.merge([map, map.visible, TileStore.instance]),
        builder: (context, _) {
          final b = map.visible.value;
          final src = map.source.bulkDownload ? map.source : openTopoMap;
          final ranges = b == null ? null : rangesFor(b, _zooms.start.round(), _zooms.end.round().clamp(0, src.maxZoom));
          final count = ranges?.fold<int>(0, (a, r) => a + r.count);
          final job = _job;
          return ListView(padding: const EdgeInsets.all(12), children: [
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('Скачать область', style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: 4),
                  Text(
                    'Берётся область, видимая сейчас на вкладке «Карта». Подложка: ${src.name}. '
                    'Скачивайте заранее, пока есть интернет: в поле карта работает из памяти.',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                  const SizedBox(height: 8),
                  Text('Масштабы ${_zooms.start.round()}–${_zooms.end.round()}'),
                  RangeSlider(
                    values: _zooms,
                    min: 5,
                    max: src.maxZoom.toDouble(),
                    divisions: src.maxZoom - 5,
                    labels: RangeLabels('${_zooms.start.round()}', '${_zooms.end.round()}'),
                    onChanged: job?.running == true ? null : (v) => setState(() => _zooms = v),
                  ),
                  Text(count == null
                      ? 'Область не выбрана'
                      : 'Тайлов: $count, примерно ${formatBytes(estimateBytes(count))}'
                          '${count > maxTilesPerDownload ? ' — больше лимита $maxTilesPerDownload' : ''}'),
                  const SizedBox(height: 8),
                  if (job != null && job.running) ...[
                    LinearProgressIndicator(value: job.total == 0 ? null : job.done / job.total),
                    const SizedBox(height: 4),
                    Text('${job.done} из ${job.total}, уже были ${job.skipped}, ошибок ${job.failed}'),
                    TextButton(onPressed: job.cancel, child: const Text('Остановить')),
                  ] else
                    FilledButton.icon(
                      icon: const Icon(Icons.download),
                      onPressed: count == null || count > maxTilesPerDownload ? null : () => _download(map),
                      label: const Text('Скачать'),
                    ),
                ]),
              ),
            ),
            const SizedBox(height: 8),
            Text('Подложки', style: Theme.of(context).textTheme.titleMedium),
            for (final s in TileStore.instance.sources)
              Card(
                child: ListTile(
                  leading: Icon(s.isMbtiles ? Icons.sd_storage : Icons.public),
                  title: Text(s.name),
                  subtitle: Text('${s.description}\n'
                      '${_sizes[s.id] == null ? '…' : s.isMbtiles ? formatBytes(_sizes[s.id]!.$1) : 'В памяти: ${_sizes[s.id]!.$2} тайлов, ${formatBytes(_sizes[s.id]!.$1)}'}'),
                  isThreeLine: true,
                  selected: s.id == map.source.id,
                  onTap: () => map.setSource(s),
                  trailing: IconButton(
                    tooltip: s.isMbtiles ? 'Удалить файл' : 'Очистить кэш',
                    icon: const Icon(Icons.delete_outline),
                    onPressed: () async {
                      if (!await _confirm(s.isMbtiles
                          ? 'Удалить карту «${s.name}» из приложения?'
                          : 'Удалить сохранённые тайлы «${s.name}»? Без сети карта этих мест не откроется.')) {
                        return;
                      }
                      if (s.isMbtiles) {
                        if (map.source.id == s.id) await map.setSource(openTopoMap);
                        await TileStore.instance.removeMbtiles(s);
                      } else {
                        await TileStore.instance.clearCache(s);
                      }
                      _sizes.remove(s.id);
                      _refreshSizes();
                    },
                  ),
                ),
              ),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              icon: const Icon(Icons.file_open),
              onPressed: _import,
              label: const Text('Добавить файл MBTiles'),
            ),
            Padding(
              padding: const EdgeInsets.all(8),
              child: Text(
                'Растровые MBTiles (png/jpg/webp) с любой картой, например спутниковой или топографической, '
                'подготовленные заранее на компьютере. Файл копируется в приложение.',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
          ]);
        },
      ),
    );
  }
}
