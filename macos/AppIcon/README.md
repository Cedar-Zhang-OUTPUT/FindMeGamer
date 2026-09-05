# App icon

`AppIcon.icns` packages the existing `../Design/FindMeGamer-Logo-Concept.png` as the macOS application icon. The artwork is preserved; only format and resolution conversion are performed.

Regenerate after changing the source:

```sh
bash script/build_app_icon.sh
```

The icon set contains 16, 32, 128, 256, and 512 point representations at 1× and 2× (up to 1024 pixels), generated with Apple's `sips` and `iconutil`.

Both development and release packaging copy this file to `Contents/Resources/AppIcon.icns` and declare `CFBundleIconFile = AppIcon` in `Info.plist`. The icon is copied before release signing. It belongs to the app bundle, not to the SwiftPM auxiliary resource bundle.
