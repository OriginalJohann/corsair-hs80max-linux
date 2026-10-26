{
  description = "Corsair HS80 Max – GNOME status service & extension";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05";
  };

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
    in
    {
      # NixOS module – import in your NixOS config:
      #   imports = [ (inputs.corsair-hs80max-linux ? hs80max) ];
      # or via flake inputs:
      #   corsair-hs80max-linux = { url = "github:OriginalJohann/corsair-hs80max-linux"; };
      #   imports = [ corsair-hs80max-linux.hs80max ];
      nixosModules.hs80max = ./service/nixos/hs80max.nix;

      # Package: the hs80max-service wrapper script
      packages.${system}.hs80max-service = pkgs.writeScriptBin "hs80max-service" ''
        #!${pkgs.python3}/bin/python3
        import sys
        sys.path.insert(0, "${self}/service")
        from hs80max_service.main import main
        sys.exit(main())
      '';
    };
}