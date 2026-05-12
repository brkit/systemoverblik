import asyncio
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Tuple

from jinja2 import Environment, FileSystemLoader, select_autoescape
from kitos_client import KitosClientManager


def is_valid_it_system_usage(usage: dict[str, Any]) -> bool:
    """Return True if the usage has general.validity.valid == True."""
    return usage.get("general", {}).get("validity", {}).get("valid", False)


def extract_usage_ids(usage: dict[str, Any]) -> Tuple[str, Optional[str]]:
    """
    Extract related identifiers from an IT system usage.

    Returns:
        (system_uuid, contract_uuid or None)
    """
    system_ctx = usage["systemContext"]
    system_uuid = system_ctx["uuid"]

    general = usage.get("general") or {}
    main_contract = general.get("mainContract") or {}
    contract_uuid = main_contract.get("uuid")

    return system_uuid, contract_uuid


async def fetch_related_kitos_objects(
    manager: KitosClientManager,
    system_uuid: str,
    contract_uuid: Optional[str],
) -> Tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]:
    """
    Fetch related objects from KITOS in parallel.

    Returns:
        (system, contract) where either can be None if missing or 404.
    """
    tasks = [manager.it_systems.get_by_uuid(system_uuid)]
    if contract_uuid:
        tasks.append(manager.it_contracts.get_by_uuid(contract_uuid))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    system = results[0] if not isinstance(results[0], Exception) else None
    contract: Optional[dict[str, Any]] = None
    if contract_uuid and len(results) > 1 and not isinstance(results[1], Exception):
        contract = results[1]

    return system, contract


def transform_roles(roles: list[dict[str, Any]]) -> dict[str, str]:
    """
    Transform roles array into a dictionary mapping user names to role names.

    Args:
        roles: List of role objects from KITOS API

    Returns:
        Dictionary with format {user.name: role.name}
    """
    roles_dict = {}
    for role in roles:
        user_info = role.get("user") or {}
        user_name = user_info.get("name")
        role_info = role.get("role") or {}
        role_name = role_info.get("name")

        if user_name and role_name and "Systemadministrator" in role_name:
            roles_dict[user_name] = role_name

    return roles_dict


def transform_external_references(references: list[dict[str, Any]]) -> list[dict[str, str]]:
    """
    Transform externalReferences array into a list of {title, url} dictionaries.

    Args:
        references: List of external reference objects from KITOS API

    Returns:
        List of dictionaries with format [{title: str, url: str}, ...]
    """
    ref_list = []
    for ref in references:
        title = ref.get("title")
        url = ref.get("url")

        if title and url:
            ref_list.append({"title": title, "url": url})

    return ref_list


def build_enriched_usage(
    usage: dict[str, Any], system: Optional[dict[str, Any]], contract: Optional[dict[str, Any]]
) -> dict[str, Any]:
    """
    Build the final enriched usage object from raw usage and fetched data.
    """
    system_ctx = usage["systemContext"]

    supplier_info = ((contract or {}).get("supplier") or {}).get("organization") or {}
    supplier = supplier_info.get("name")

    org_usage = usage.get("organizationUsage") or {}
    responsible_unit = (org_usage.get("responsibleOrganizationUnit") or {}).get("name")

    using_units = [
        unit_name
        for unit_name in (unit.get("name") for unit in (org_usage.get("usingOrganizationUnits") or []))
        if unit_name
    ]

    return {
        "name": system_ctx["name"],
        "description": system.get("description") if system else None,
        "supplier": supplier,
        "responsibleOrganizationUnit": responsible_unit,
        "usingOrganizationUnits": using_units,
        "roles": transform_roles(usage.get("roles", [])),
        "externalReferences": transform_external_references(usage.get("externalReferences", [])),
    }


def _write_json_file(output_path: Path, data: list[dict[str, Any]]) -> None:
    """Write JSON data to a single file path."""
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def write_data_to_file(
    data: list[dict[str, Any]], output_dir: str = "dist", filename: str = "data.json"
) -> Tuple[str, Optional[str]]:
    """
    Write enriched data to a JSON file in the specified directory.

    Args:
        data: List of enriched IT system usage objects
        output_dir: Directory to write the file to (default: "dist")
        filename: Name of the output file (default: "data.json")

    Returns:
        Tuple of (path to the written file, optional warning message)
    """
    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)
    output_path = output_dir_path / filename

    try:
        _write_json_file(output_path, data)
        return str(output_path), None
    except PermissionError as exc:
        fallback_suffix = output_path.suffix or ".json"
        fallback_path = output_dir_path / (
            f"{output_path.stem}-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}{fallback_suffix}"
        )
        _write_json_file(fallback_path, data)
        warning = (
            f"Could not overwrite {output_path} ({exc}). "
            "This usually means another program has the file locked. "
            f"Wrote JSON to {fallback_path} instead."
        )
        return str(fallback_path), warning


async def enrich_single_it_system_usage(manager: KitosClientManager, usage: dict[str, Any]) -> dict[str, Any]:
    """
    Orchestrate enrichment for a single IT system usage.
    """
    system_uuid, contract_uuid = extract_usage_ids(usage)
    system, contract = await fetch_related_kitos_objects(manager, system_uuid, contract_uuid)
    return build_enriched_usage(usage, system, contract)


def generate_html_from_template(data: list[dict[str, Any]], output_path: str) -> None:
    """Generate HTML from Jinja2 template and in-memory data."""
    env = Environment(
        loader=FileSystemLoader("."),
        autoescape=select_autoescape(["html", "xml"]),
    )

    tmpl = env.get_template("jinja_template")

    html = tmpl.render(
        systems=data,
        systems_json=json.dumps(data, ensure_ascii=False),
        generation_timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    out_path = Path(output_path)
    out_path.write_text(html, encoding="utf-8")


def save_html_to_webserver(local_html_path: str, webserver_filename: str = "index.html") -> None:
    """Save the generated HTML file to the webserver."""
    webserver_root = os.getenv("PATH_TO_WEBSERVER")
    if not webserver_root:
        raise ValueError("PATH_TO_WEBSERVER environment variable not found")

    webserver_path = Path(webserver_root)
    destination_path = webserver_path / webserver_filename

    try:
        # We only need the file contents on the webserver. Avoid copy2 here because
        # preserving local metadata on a network share can trigger PermissionError.
        shutil.copyfile(local_html_path, destination_path)
    except PermissionError as exc:
        raise PermissionError(f"Could not write to '{destination_path}'") from exc


async def main() -> None:
    """Fetch valid IT system usages from KITOS, write to dist/data.json, and generate HTML."""
    async with KitosClientManager(email=os.getenv("KITOS_USERNAME"), password=os.getenv("PASSWORD")) as kitos:
        all_usages = await kitos.it_system_usages.get_all()
        valid_usages = [u for u in all_usages if is_valid_it_system_usage(u)]

        if not valid_usages:
            sys.stdout.write("No valid IT system usages found\n")
            return

        enriched = await asyncio.gather(*(enrich_single_it_system_usage(kitos, u) for u in valid_usages))

        # Write data to JSON file
        json_path, json_warning = write_data_to_file(enriched)
        sys.stdout.write(f"Successfully wrote {len(enriched)} IT systems to {json_path}\n")
        if json_warning:
            sys.stdout.write(f"Warning: {json_warning}\n")

        # Generate HTML from template
        html_path = os.path.join("dist", "index.html")
        generate_html_from_template(enriched, html_path)
        sys.stdout.write(f"Successfully generated HTML to {html_path}\n")

        # Optionally save to webserver if PATH_TO_WEBSERVER is set
        if os.getenv("PATH_TO_WEBSERVER"):
            try:
                save_html_to_webserver(html_path)
                sys.stdout.write("Successfully deployed to webserver\n")
            except Exception as e:
                sys.stdout.write(f"Warning: Could not deploy to webserver: {e}\n")


if __name__ == "__main__":
    asyncio.run(main())
