{ pkgs ? import <nixpkgs> {} }:

# Test environment: runs the project's pytest suite (service/).
#
#   nix-shell shells/test.nix --command "python3 -m pytest service/ -v"
#
pkgs.mkShell {
  SHELL = "${pkgs.bash}/bin/bash";

  buildInputs = with pkgs; [
    python3
    python3Packages.pytest
    python3Packages.pydbus  # pulls in python3-gi (gobject) transitively
    bash
  ];
}
