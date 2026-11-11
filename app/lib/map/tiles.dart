// Offline maps: a disk cache filled while browsing, area download for sources
// that allow it, and imported raster MBTiles. Tiles come from (in order):
// MBTiles file → disk cache → network (saved to the cache).

import 'dart:async';
import 'dart:io';
import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';
import 'package:flutter/painting.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import 'package:sqflite/sqflite.dart';

const String userAgent = 'Cricket/0.1 (drone beacon finder; offline maps)';

class TileSource {
  const TileSource({
    required this.id,
    required this.name,
    required this.description,
    this.url,
    this.mbtilesPath,
    required this.minZoom,
    required this.maxZoom,
    required this.attribution,
    this.bulkDownload = false,
  });

  final String id;
  final String name;
  final String description;
  final String? url; // {z}/{x}/{y}
  final String? mbtilesPath;
  final int minZoom;
  final int maxZoom;
  final String attribution;

  /// Area download is offered only where the tile server's policy tolerates it.
  /// openstreetmap.org forbids bulk downloading, so OSM is cached only while
  /// browsing.
  final bool bulkDownload;

  bool get isMbtiles => mbtilesPath != null;
}

/// OpenTopoMap shows relief: contour lines, hill shading, forest, tracks,
/// which is what matters when searching a field or forest.
const openTopoMap = TileSource(
  id: 'opentopomap',
  name: 'OpenTopoMap',
  description: 'Рельеф: горизонтали, отмывка, лес, тропы. До z17.',
  url: 'https://tile.opentopomap.org/{z}/{x}/{y}.png',
  minZoom: 0,
  maxZoom: 17,
  attribution: '© OpenStreetMap contributors, SRTM | © OpenTopoMap (CC-BY-SA)',
  bulkDownload: true,
);

const osmStandard = TileSource(
  id: 'osm',
  name: 'OpenStreetMap',
  description: 'Обычная карта OSM. Офлайн — только просмотренные места.',
  url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
  minZoom: 0,
  maxZoom: 19,
  attribution: '© OpenStreetMap contributors',
);

const builtinSources = [openTopoMap, osmStandard];

// ---------------------------------------------------------------- tile math

class TileRange {
  TileRange(this.z, this.minX, this.maxX, this.minY, this.maxY);
  final int z, minX, maxX, minY, maxY;
  int get count => (maxX - minX + 1) * (maxY - minY + 1);
}

int lonToTileX(double lon, int z) => ((lon + 180) / 360 * (1 << z)).floor().clamp(0, (1 << z) - 1);

int latToTileY(double lat, int z) {
  final r = lat.clamp(-85.0511, 85.0511) * math.pi / 180;
  final y = (1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * (1 << z);
  return y.floor().clamp(0, (1 << z) - 1);
}

List<TileRange> rangesFor(LatLngBounds b, int minZ, int maxZ) => [
      for (var z = minZ; z <= maxZ; z++)
        TileRange(z, lonToTileX(b.west, z), lonToTileX(b.east, z), latToTileY(b.north, z),
            latToTileY(b.south, z)),
    ];

// ---------------------------------------------------------------- storage

class TileStore extends ChangeNotifier {
  TileStore._();
  static final TileStore instance = TileStore._();

  late Directory _root;
  late Directory _mbDir;
  final List<TileSource> imported = [];
  final Map<String, Database> _dbs = {};
  final http.Client _client = http.Client();
  DateTime _offlineUntil = DateTime.fromMillisecondsSinceEpoch(0);

  List<TileSource> get sources => [...builtinSources, ...imported];

  Future<void> init() async {
    final base = await getApplicationSupportDirectory();
    _root = Directory('${base.path}/tiles');
    _mbDir = Directory('${base.path}/mbtiles');
    await _root.create(recursive: true);
    await _mbDir.create(recursive: true);
    for (final f in _mbDir.listSync().whereType<File>()) {
      if (f.path.endsWith('.mbtiles')) {
        try {
          imported.add(await _openMbtiles(f.path));
        } catch (e) {
          debugPrint('MBTiles ${f.path}: $e');
        }
      }
    }
  }

  File _file(TileSource s, int z, int x, int y) => File('${_root.path}/${s.id}/$z/$x/$y.png');

  Future<Uint8List?> getTile(TileSource s, int z, int x, int y, {bool network = true}) async {
    if (s.isMbtiles) {
      final db = _dbs[s.id];
      if (db == null) return null;
      final rows = await db.rawQuery(
        'SELECT tile_data FROM tiles WHERE zoom_level = ? AND tile_column = ? AND tile_row = ?',
        [z, x, (1 << z) - 1 - y],
      );
      return rows.isEmpty ? null : rows.first['tile_data'] as Uint8List;
    }
    final f = _file(s, z, x, y);
    if (await f.exists()) return f.readAsBytes();
    if (!network || DateTime.now().isBefore(_offlineUntil)) return null;
    return _fetch(s, z, x, y);
  }

  Future<Uint8List?> _fetch(TileSource s, int z, int x, int y) async {
    final url = s.url!.replaceAll('{z}', '$z').replaceAll('{x}', '$x').replaceAll('{y}', '$y');
    try {
      final r = await _client
          .get(Uri.parse(url), headers: {'User-Agent': userAgent})
          .timeout(const Duration(seconds: 15));
      if (r.statusCode != 200 || r.bodyBytes.isEmpty) return null;
      final f = _file(s, z, x, y);
      await f.parent.create(recursive: true);
      await f.writeAsBytes(r.bodyBytes, flush: false);
      return r.bodyBytes;
    } on SocketException {
      // No network: stop trying for a while so offline panning stays fast.
      _offlineUntil = DateTime.now().add(const Duration(seconds: 20));
      return null;
    } on TimeoutException {
      _offlineUntil = DateTime.now().add(const Duration(seconds: 20));
      return null;
    } catch (_) {
      return null;
    }
  }

  Future<bool> hasTile(TileSource s, int z, int x, int y) => _file(s, z, x, y).exists();

  /// Bytes and file count of the cache of one source.
  Future<(int, int)> cacheSize(TileSource s) async {
    if (s.isMbtiles) return (await File(s.mbtilesPath!).length(), 0);
    final d = Directory('${_root.path}/${s.id}');
    if (!await d.exists()) return (0, 0);
    var bytes = 0, files = 0;
    await for (final e in d.list(recursive: true)) {
      if (e is File) {
        bytes += await e.length();
        files++;
      }
    }
    return (bytes, files);
  }

  Future<void> clearCache(TileSource s) async {
    final d = Directory('${_root.path}/${s.id}');
    if (await d.exists()) await d.delete(recursive: true);
    notifyListeners();
  }

  // ---------------------------------------------------------------- MBTiles

  Future<TileSource> _openMbtiles(String path) async {
    final db = await openDatabase(path, readOnly: true, singleInstance: false);
    final meta = <String, String>{};
    for (final r in await db.rawQuery('SELECT name, value FROM metadata')) {
      meta[r['name'] as String] = '${r['value']}';
    }
    final format = meta['format'] ?? 'png';
    if (format == 'pbf' || format == 'mvt') {
      await db.close();
      throw const FormatException('Векторные MBTiles не поддерживаются, нужны растровые (png/jpg/webp)');
    }
    var minZ = int.tryParse(meta['minzoom'] ?? '');
    var maxZ = int.tryParse(meta['maxzoom'] ?? '');
    if (minZ == null || maxZ == null) {
      final r = await db.rawQuery('SELECT MIN(zoom_level) a, MAX(zoom_level) b FROM tiles');
      minZ ??= r.first['a'] as int? ?? 0;
      maxZ ??= r.first['b'] as int? ?? 18;
    }
    final id = 'mb:${path.split('/').last}';
    _dbs[id] = db;
    return TileSource(
      id: id,
      name: meta['name'] ?? path.split('/').last,
      description: 'MBTiles, $format, z$minZ–$maxZ',
      mbtilesPath: path,
      minZoom: minZ,
      maxZoom: maxZ,
      attribution: meta['attribution'] ?? '',
    );
  }

  Future<TileSource> importMbtiles(String srcPath) async {
    final name = srcPath.split('/').last;
    final dst = '${_mbDir.path}/${name.endsWith('.mbtiles') ? name : '$name.mbtiles'}';
    await File(srcPath).copy(dst);
    try {
      final s = await _openMbtiles(dst);
      imported.removeWhere((e) => e.id == s.id);
      imported.add(s);
      notifyListeners();
      return s;
    } catch (_) {
      await File(dst).delete();
      rethrow;
    }
  }

  Future<void> removeMbtiles(TileSource s) async {
    await _dbs.remove(s.id)?.close();
    imported.removeWhere((e) => e.id == s.id);
    await File(s.mbtilesPath!).delete();
    notifyListeners();
  }
}

// ---------------------------------------------------------------- area download

class AreaDownload extends ChangeNotifier {
  AreaDownload(this.source, this.ranges);
  final TileSource source;
  final List<TileRange> ranges;
  int done = 0, skipped = 0, failed = 0;
  bool running = false, cancelled = false;

  int get total => ranges.fold(0, (a, r) => a + r.count);

  Future<void> run({int parallel = 2}) async {
    running = true;
    notifyListeners();
    final store = TileStore.instance;
    final it = _tiles().iterator;
    // Workers share the iterator; Dart runs them on one event loop.
    (int, int, int)? next() => it.moveNext() ? it.current : null;

    Future<void> worker() async {
      for (var t = next(); t != null && !cancelled; t = next()) {
        final (z, x, y) = t;
        if (await store.hasTile(source, z, x, y)) {
          skipped++;
        } else if (await store._fetch(source, z, x, y) == null) {
          failed++;
        }
        done++;
        if (done % 10 == 0) notifyListeners();
      }
    }

    await Future.wait([for (var i = 0; i < parallel; i++) worker()]);
    running = false;
    notifyListeners();
  }

  Iterable<(int, int, int)> _tiles() sync* {
    for (final r in ranges) {
      for (var x = r.minX; x <= r.maxX; x++) {
        for (var y = r.minY; y <= r.maxY; y++) {
          yield (r.z, x, y);
        }
      }
    }
  }

  void cancel() {
    cancelled = true;
    notifyListeners();
  }
}

// ---------------------------------------------------------------- flutter_map glue

class OfflineTileProvider extends TileProvider {
  OfflineTileProvider(this.source);
  final TileSource source;

  @override
  ImageProvider getImage(TileCoordinates coordinates, TileLayer options) =>
      _TileImage(source, coordinates.z, coordinates.x, coordinates.y);
}

@immutable
class _TileImage extends ImageProvider<_TileImage> {
  const _TileImage(this.source, this.z, this.x, this.y);
  final TileSource source;
  final int z, x, y;

  @override
  Future<_TileImage> obtainKey(ImageConfiguration configuration) => SynchronousFuture(this);

  @override
  ImageStreamCompleter loadImage(_TileImage key, ImageDecoderCallback decode) =>
      MultiFrameImageStreamCompleter(codec: _load(decode), scale: 1);

  Future<ui.Codec> _load(ImageDecoderCallback decode) async {
    final bytes = await TileStore.instance.getTile(source, z, x, y);
    if (bytes == null) {
      // Let the cache forget the failure so the tile is retried later.
      scheduleMicrotask(() => PaintingBinding.instance.imageCache.evict(this));
      throw StateError('tile $z/$x/$y unavailable');
    }
    return decode(await ui.ImmutableBuffer.fromUint8List(bytes));
  }

  @override
  bool operator ==(Object other) =>
      other is _TileImage && other.source.id == source.id && other.z == z && other.x == x && other.y == y;

  @override
  int get hashCode => Object.hash(source.id, z, x, y);
}

String formatBytes(int b) {
  if (b < 1024) return '$b Б';
  if (b < 1024 * 1024) return '${(b / 1024).toStringAsFixed(0)} КБ';
  return '${(b / 1024 / 1024).toStringAsFixed(1)} МБ';
}

/// Rough size estimate of a download: OpenTopoMap tiles average ~25 KB.
int estimateBytes(int tiles) => tiles * 25 * 1024;
