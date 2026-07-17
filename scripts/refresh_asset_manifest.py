from app.services.assets import refresh_asset_manifest


def main() -> None:
    manifest = refresh_asset_manifest()
    for asset in manifest.assets:
        state = "valid" if asset.valid else f"invalid: {asset.error}"
        print(f"{asset.relative_path}: {state}")  # noqa: T201


if __name__ == "__main__":
    main()

