{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell {
	
  SHELL = "${pkgs.bash}/bin/bash";
	
  buildInputs = with pkgs; [
    php83
    php83Packages.composer
    nodejs_latest
    stdenv.cc.cc.lib
    python3
    python3Packages.pip
    python3Packages.virtualenv
    python3Packages.pymysql
    git
    bash
  ];

  shellHook = ''
    echo "Entwicklungsumgebung geladen!"
    
    # Setzt den Pfad zur libstdc++ aus den Build-Inputs für die Shell-Sitzung
    export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib:$LD_LIBRARY_PATH"
    
    # Startet Antigravity direkt aus der Umgebung heraus, 
    # sodass es die PHP-Pfade automatisch im Zugriff hat
    GTK_USE_PORTAL=1 \
    NIXOS_OZONE_WL=0 \
    code --disable-gpu --ozone-platform=x11 . &
  '';
}
