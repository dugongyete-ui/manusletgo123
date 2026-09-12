{pkgs}: {
  deps = [
    pkgs.procps
    pkgs.xvfb-run
    pkgs.chromium
    pkgs.x11vnc
    pkgs.xorg.xorgserver
  ];
}
