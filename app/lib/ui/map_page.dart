import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../app.dart';
import '../map/tiles.dart';
import '../state/locator.dart';
import 'beacons_page.dart';
import 'widgets.dart';

class MapPage extends StatefulWidget {
  const MapPage({super.key});
  @override
  State<MapPage> createState() => _MapPageState();
}

class _MapPageState extends State<MapPage> {
  final _controller = MapController();
  LatLng _initial = const LatLng(48, 68);
  double _initialZoom = 4;
  bool _loaded = false;
  bool _follow = false;
  Timer? _saveTimer;
  MapState? _map;

  @override
  void initState() {
    super.initState();
    SharedPreferences.getInstance().then((p) {
      final lat = p.getDouble('map_lat'), lon = p.getDouble('map_lon');
      if (lat != null && lon != null) {
        _initial = LatLng(lat, lon);
        _initialZoom = p.getDouble('map_zoom') ?? 14;
      }
      setState(() => _loaded = true);
    });
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _map?.removeListener(_onMapState);
    _map = Services.of(context).map..addListener(_onMapState);
  }

  @override
  void dispose() {
    _map?.removeListener(_onMapState);
    _saveTimer?.cancel();
    super.dispose();
  }

  void _onMapState() {
    final f = _map?.focus;
    if (f != null && _loaded) {
      _map!.focus = null;
      try {
        _controller.move(f, math.max(_controller.camera.zoom, 16));
      } catch (_) {
        _initial = f;
        _initialZoom = 16;
      }
    }
    if (mounted) setState(() {});
  }

  void _onCamera(MapCamera camera, bool gesture) {
    final m = Services.of(context).map;
    m.visible.value = camera.visibleBounds;
    m.zoom = camera.zoom;
    if (gesture) _follow = false;
    _saveTimer?.cancel();
    _saveTimer = Timer(const Duration(seconds: 2), () async {
      final p = await SharedPreferences.getInstance();
      await p.setDouble('map_lat', camera.center.latitude);
      await p.setDouble('map_lon', camera.center.longitude);
      await p.setDouble('map_zoom', camera.zoom);
    });
  }

  @override
  Widget build(BuildContext context) {
    final s = Services.of(context);
    if (!_loaded) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    return Scaffold(
      appBar: AppBar(
        title: const Text('Карта'),
        actions: [
          PopupMenuButton<TileSource>(
            icon: const Icon(Icons.layers),
            tooltip: 'Подложка',
            onSelected: s.map.setSource,
            itemBuilder: (_) => [
              for (final src in TileStore.instance.sources)
                CheckedPopupMenuItem(value: src, checked: src.id == s.map.source.id, child: Text(src.name)),
            ],
          ),
        ],
      ),
      body: ListenableBuilder(
        listenable: Listenable.merge([s.beacons, s.position, s.locator, s.map]),
        builder: (context, _) {
          final pos = s.position.last;
          final me = pos == null ? null : LatLng(pos.latitude, pos.longitude);
          if (_follow && me != null) {
            WidgetsBinding.instance.addPostFrameCallback((_) {
              try {
                _controller.move(me, _controller.camera.zoom);
              } catch (_) {}
            });
          }
          final loc = s.locator;
          final est = loc.result;
          final src = s.map.source;
          return Stack(children: [
            FlutterMap(
              mapController: _controller,
              options: MapOptions(
                initialCenter: _initial,
                initialZoom: _initialZoom,
                minZoom: 2,
                maxZoom: 20,
                onPositionChanged: _onCamera,
                onMapReady: () => _onCamera(_controller.camera, false),
              ),
              children: [
                TileLayer(
                  key: ValueKey(src.id),
                  tileProvider: OfflineTileProvider(src),
                  minNativeZoom: src.minZoom,
                  maxNativeZoom: src.maxZoom,
                  maxZoom: 20,
                  userAgentPackageName: 'dev.cricket.cricket',
                ),
                if (est != null)
                  PolygonLayer(polygons: [
                    for (final c in est.cells)
                      Polygon(
                        points: _square(c.center, c.halfSizeM),
                        color: Colors.red.withValues(alpha: 0.12 + 0.45 * c.likelihood),
                      ),
                  ]),
                CircleLayer(circles: [
                  if (pos != null && me != null)
                    CircleMarker(
                      point: me,
                      radius: pos.accuracy,
                      useRadiusInMeter: true,
                      color: Colors.blue.withValues(alpha: 0.15),
                      borderColor: Colors.blue,
                      borderStrokeWidth: 1,
                    ),
                  for (final p in loc.current)
                    CircleMarker(
                      point: LatLng(p.lat, p.lon),
                      radius: 5,
                      color: heatColor(rssiFraction(p.rssi)),
                    ),
                  if (est != null)
                    CircleMarker(
                      point: est.best,
                      radius: est.radiusM,
                      useRadiusInMeter: true,
                      color: Colors.transparent,
                      borderColor: Colors.red,
                      borderStrokeWidth: 2,
                    ),
                ]),
                MarkerLayer(markers: [
                  for (final r in s.beacons.beacons.values)
                    if (r.status.hasPosition)
                      Marker(
                        point: LatLng(r.status.lat, r.status.lon),
                        width: 140,
                        height: 56,
                        alignment: Alignment.topCenter,
                        child: _Pin(
                          label: '${s.beacons.labelOf(r.id)}\nGPS ${formatAge(Duration(seconds: r.status.positionAgeS))}',
                          color: r.status.mode.isLost ? Colors.red : Colors.deepPurple,
                        ),
                      ),
                  if (est != null)
                    Marker(
                      point: est.best,
                      width: 30,
                      height: 30,
                      child: const Icon(Icons.close, color: Colors.red, size: 30),
                    ),
                  if (me != null)
                    Marker(
                      point: me,
                      width: 18,
                      height: 18,
                      child: Container(
                        decoration: BoxDecoration(
                          color: Colors.blue,
                          shape: BoxShape.circle,
                          border: Border.all(color: Colors.white, width: 3),
                        ),
                      ),
                    ),
                ]),
                RichAttributionWidget(
                  attributions: [TextSourceAttribution(src.attribution)],
                ),
              ],
            ),
            Positioned(
              right: 12,
              top: 12,
              child: FloatingActionButton.small(
                heroTag: 'me',
                tooltip: 'Где я',
                onPressed: me == null
                    ? null
                    : () {
                        setState(() => _follow = true);
                        _controller.move(me, math.max(_controller.camera.zoom, 16));
                      },
                child: Icon(_follow ? Icons.my_location : Icons.location_searching),
              ),
            ),
            if (s.position.error != null)
              Positioned(left: 12, top: 12, right: 64, child: Card(child: Padding(padding: const EdgeInsets.all(8), child: Text(s.position.error!)))),
            if (loc.target != null) Positioned(left: 8, right: 8, bottom: 8, child: _LocatorPanel(services: s)),
          ]);
        },
      ),
    );
  }

  List<LatLng> _square(LatLng c, double half) {
    final dLat = half / 111320.0;
    final dLon = half / (111320.0 * math.cos(c.latitude * math.pi / 180));
    return [
      LatLng(c.latitude - dLat, c.longitude - dLon),
      LatLng(c.latitude - dLat, c.longitude + dLon),
      LatLng(c.latitude + dLat, c.longitude + dLon),
      LatLng(c.latitude + dLat, c.longitude - dLon),
    ];
  }
}

class _Pin extends StatelessWidget {
  const _Pin({required this.label, required this.color});
  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) => Column(mainAxisSize: MainAxisSize.min, children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 1),
          decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(4)),
          child: Text(label,
              textAlign: TextAlign.center,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(color: Colors.white, fontSize: 11)),
        ),
        Icon(Icons.place, color: color, size: 22),
      ]);
}

class _LocatorPanel extends StatelessWidget {
  const _LocatorPanel({required this.services});
  final Services services;

  @override
  Widget build(BuildContext context) {
    final loc = services.locator;
    final id = loc.target!;
    final r = services.beacons.beacons[id];
    final Estimate? est = loc.result;
    final n = loc.current.length;
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 4, 4, 4),
        child: Row(children: [
          SignalBars(rssi: r != null && r.fresh ? r.smoothRssi : null, size: 22),
          const SizedBox(width: 10),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
              Text(services.beacons.labelOf(id), style: Theme.of(context).textTheme.titleSmall),
              Text(
                est != null
                    ? 'Точек $n, область ±${est.radiusM.round()} м'
                    : (n < 4 ? 'Точек $n, нужно хотя бы 4 в разных местах' : 'Точек $n, отойдите дальше друг от друга'),
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ]),
          ),
          IconButton(
            tooltip: loc.recording ? 'Остановить запись' : 'Записывать',
            icon: Icon(loc.recording ? Icons.pause_circle : Icons.fiber_manual_record,
                color: loc.recording ? null : Colors.red),
            onPressed: () => loc.setRecording(!loc.recording),
          ),
          if (est != null)
            IconButton(
              tooltip: 'К оценке',
              icon: const Icon(Icons.center_focus_strong),
              onPressed: () => services.showMap(focus: est.best),
            ),
        ]),
      ),
    );
  }
}
