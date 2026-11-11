import 'package:flutter/material.dart';

/// Four bars for RSSI −100…−50 dBm; null = not heard.
class SignalBars extends StatelessWidget {
  const SignalBars({super.key, required this.rssi, this.size = 28});
  final double? rssi;
  final double size;

  @override
  Widget build(BuildContext context) {
    final level = rssi == null ? 0 : (((rssi! + 100) / 12.5).clamp(0, 4)).ceil();
    final on = Theme.of(context).colorScheme.primary;
    final off = Theme.of(context).colorScheme.outlineVariant;
    return SizedBox(
      width: size,
      height: size,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        mainAxisAlignment: MainAxisAlignment.spaceEvenly,
        children: [
          for (var i = 1; i <= 4; i++)
            Container(width: size / 6, height: size * i / 4, color: i <= level ? on : off),
        ],
      ),
    );
  }
}

/// Signal strength as a 0..1 fraction for the hot-cold gauge.
double rssiFraction(double rssi) => ((rssi + 105) / 65).clamp(0.0, 1.0);

Color heatColor(double f) => Color.lerp(Colors.blue, Colors.red, f)!;

void showSnack(BuildContext context, String text) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(text)));
}
