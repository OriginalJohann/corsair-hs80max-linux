{
  description = "Corsair HS80 Max – GNOME status service & extension";

  # Import in your NixOS flake config:
  #   inputs.corsair-hs80max-linux.url = "github:OriginalJohann/corsair-hs80max-linux";
  #   modules = [ ... corsair-hs80max-linux.nixosModules.hs80max ];
  #   services.hs80max.enable = true;
  #
  # No own inputs: the module's `pkgs` come from the host flake, so the
  # build always tracks the host's nixpkgs.
  outputs = { self }: {
    nixosModules.hs80max = ./service/nixos/hs80max.nix;
  };
}