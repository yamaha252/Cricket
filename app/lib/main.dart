import 'package:flutter/material.dart';

import 'app.dart';
import 'map/tiles.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await TileStore.instance.init();
  runApp(CricketApp(services: Services.create()));
}
