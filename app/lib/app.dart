import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'map/tiles.dart';
import 'state/beacons.dart';
import 'state/locator.dart';
import 'state/position.dart';
import 'ui/beacons_page.dart';
import 'ui/map_page.dart';
import 'ui/offline_maps_page.dart';

/// Map view state shared between the map and the offline-maps pages.
class MapState extends ChangeNotifier {
  TileSource source = openTopoMap;
  /// Visible map area, updated while the map moves.
  final ValueNotifier<LatLngBounds?> visible = ValueNotifier(null);
  double zoom = 15;

  /// Set by other pages to centre the map on something.
  LatLng? focus;

  void setFocus(LatLng p) {
    focus = p;
    notifyListeners();
  }

  static const _prefSource = 'map_source';

  Future<void> load() async {
    final p = await SharedPreferences.getInstance();
    final id = p.getString(_prefSource);
    source = TileStore.instance.sources.firstWhere((s) => s.id == id, orElse: () => openTopoMap);
    notifyListeners();
  }

  Future<void> setSource(TileSource s) async {
    source = s;
    notifyListeners();
    final p = await SharedPreferences.getInstance();
    await p.setString(_prefSource, s.id);
  }
}

class Services extends InheritedWidget {
  const Services._({
    required this.beacons,
    required this.position,
    required this.locator,
    required this.map,
    required this.tab,
    required super.child,
  });

  factory Services.create() {
    final beacons = BeaconStore();
    final position = PositionService();
    return Services._(
      beacons: beacons,
      position: position,
      locator: LocatorService(beacons, position),
      map: MapState()..load(),
      tab: ValueNotifier(0),
      child: const SizedBox(),
    );
  }

  Services wrap(Widget child) => Services._(
        beacons: beacons,
        position: position,
        locator: locator,
        map: map,
        tab: tab,
        child: child,
      );

  final BeaconStore beacons;
  final PositionService position;
  final LocatorService locator;
  final MapState map;
  final ValueNotifier<int> tab;

  static Services of(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<Services>()!;

  /// Switches to the map tab, optionally centred on [focus].
  void showMap({LatLng? focus}) {
    if (focus != null) map.setFocus(focus);
    tab.value = 1;
  }

  @override
  bool updateShouldNotify(Services oldWidget) => false;
}

class CricketApp extends StatelessWidget {
  const CricketApp({super.key, required this.services});
  final Services services;

  @override
  Widget build(BuildContext context) {
    return services.wrap(
      MaterialApp(
        title: 'Cricket',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(colorSchemeSeed: Colors.green, useMaterial3: true),
        darkTheme: ThemeData(
            colorSchemeSeed: Colors.green, brightness: Brightness.dark, useMaterial3: true),
        home: const HomePage(),
      ),
    );
  }
}

class HomePage extends StatefulWidget {
  const HomePage({super.key});
  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> with WidgetsBindingObserver {
  bool _started = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!_started) {
      _started = true;
      final s = Services.of(context);
      // Bluetooth permissions first, then location (one dialog at a time).
      s.beacons.start().then((_) => s.position.start());
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final s = Services.of(context);
    if (state == AppLifecycleState.resumed) {
      s.beacons.start();
    } else if (state == AppLifecycleState.paused && !s.locator.recording) {
      // Keep scanning in the background only while a track is being recorded.
      s.beacons.stop();
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final tab = Services.of(context).tab;
    return ValueListenableBuilder<int>(
      valueListenable: tab,
      builder: (context, i, _) => Scaffold(
        body: IndexedStack(
          index: i,
          children: const [BeaconsPage(), MapPage(), OfflineMapsPage()],
        ),
        bottomNavigationBar: NavigationBar(
          selectedIndex: i,
          onDestinationSelected: (v) => tab.value = v,
          destinations: const [
            NavigationDestination(icon: Icon(Icons.sensors), label: 'Маячки'),
            NavigationDestination(icon: Icon(Icons.map_outlined), label: 'Карта'),
            NavigationDestination(icon: Icon(Icons.download_for_offline_outlined), label: 'Офлайн-карты'),
          ],
        ),
      ),
    );
  }
}
