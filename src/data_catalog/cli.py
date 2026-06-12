"""命令行入口"""
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

from .models import Catalog, Resource, UPDATE_FREQUENCIES, AUTHORIZATION_SCOPES
from .scanner import scan_directory
from .checker import check_catalog, has_errors, REQUIRED_FIELDS
from .publisher import filter_resources, mark_published, get_pending_publish
from .exporter import to_platform_json, to_platform_csv, generate_diff_report, save_export


console = Console()
DEFAULT_CATALOG_FILE = "catalog.json"


def _load_catalog(path: str) -> Catalog:
    p = Path(path)
    if not p.exists():
        console.print(f"[red]目录文件不存在: {path}[/red]")
        sys.exit(1)
    try:
        content = p.read_text(encoding="utf-8")
        return Catalog.from_json(content)
    except Exception as e:
        console.print(f"[red]加载目录失败: {e}[/red]")
        sys.exit(1)


def _save_catalog(catalog: Catalog, path: str) -> None:
    p = Path(path)
    p.write_text(catalog.to_json(), encoding="utf-8")


def _select_resources(
    catalog: Catalog,
    all_flag: bool,
    resource_ids: Optional[List[str]],
    tags: Optional[List[str]],
) -> List[Resource]:
    if all_flag:
        return catalog.resources
    selected = []
    if resource_ids:
        for rid in resource_ids:
            r = catalog.get_resource(rid)
            if r:
                selected.append(r)
            else:
                console.print(f"[yellow]警告: 未找到资源 ID {rid}[/yellow]")
    if tags:
        for r in catalog.resources:
            if any(t in r.tags for t in tags) and r not in selected:
                selected.append(r)
    return selected


# ============================================================
# CLI Group
# ============================================================
@click.group(help="数据要素目录命令行工具 - 批量整理可流通数据资源")
@click.version_option(version="0.1.0", prog_name="datacat")
def main():
    pass


# ============================================================
# scan 命令
# ============================================================
@main.command(help="扫描本地目录，生成数据资源清单")
@click.argument("directory", type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option("-o", "--output", "output_path", default=DEFAULT_CATALOG_FILE,
              help="输出目录清单文件路径 (默认: catalog.json)")
@click.option("--no-recursive", is_flag=True, help="不递归扫描子目录")
@click.option("--ext", "extensions", multiple=True,
              help="只包含指定文件扩展名（可多次指定），例如 --ext csv --ext xlsx")
@click.option("--merge", is_flag=True,
              help="与已存在的目录文件合并（根据文件路径去重）")
def scan(directory, output_path, no_recursive, extensions, merge):
    include_ext = set(e.lower() if e.startswith(".") else f".{e.lower()}" for e in extensions) if extensions else None

    console.print(f"[cyan]扫描目录:[/cyan] {directory}")
    try:
        catalog = scan_directory(
            root_path=directory,
            include_ext=include_ext,
            recursive=not no_recursive,
        )
    except Exception as e:
        console.print(f"[red]扫描失败: {e}[/red]")
        sys.exit(1)

    if merge and Path(output_path).exists():
        existing = _load_catalog(output_path)
        existing_paths = {r.file_path for r in existing.resources}
        new_count = 0
        for r in catalog.resources:
            if r.file_path not in existing_paths:
                existing.add_resource(r)
                new_count += 1
        catalog = existing
        console.print(f"[green]合并完成，新增 {new_count} 个资源[/green]")

    _save_catalog(catalog, output_path)
    console.print(f"[green]扫描完成，共发现 {len(catalog.resources)} 个数据资源[/green]")
    console.print(f"[blue]目录清单已保存至: {output_path}[/blue]")

    if catalog.resources:
        _print_resource_table(catalog.resources, limit=10)


# ============================================================
# describe 命令
# ============================================================
@main.command(help="补充或修改资源元信息（名称、来源、更新频率、授权范围、联系人等）")
@click.option("-c", "--catalog", "catalog_path", default=DEFAULT_CATALOG_FILE,
              help="目录清单文件路径")
@click.option("-a", "--all", "all_flag", is_flag=True, help="对所有资源执行操作")
@click.option("--id", "resource_ids", multiple=True, help="指定资源 ID（可多次指定）")
@click.option("--tag", "filter_tags", multiple=True, help="按标签筛选（可多次指定）")
@click.option("--name", help="资源名称")
@click.option("--source", help="数据来源")
@click.option("--frequency", "update_frequency",
              type=click.Choice(UPDATE_FREQUENCIES),
              help=f"更新频率 (可选: {', '.join(UPDATE_FREQUENCIES)})")
@click.option("--scope", "authorization_scope",
              type=click.Choice(AUTHORIZATION_SCOPES),
              help=f"授权范围 (可选: {', '.join(AUTHORIZATION_SCOPES)})")
@click.option("--contact-name", help="联系人姓名")
@click.option("--contact-email", help="联系人邮箱")
@click.option("--description", help="资源描述")
@click.option("--custom", "custom_fields", multiple=True,
              help="自定义字段，格式 key=value（可多次指定）")
def describe(catalog_path, all_flag, resource_ids, filter_tags, name, source,
             update_frequency, authorization_scope, contact_name, contact_email,
             description, custom_fields):
    catalog = _load_catalog(catalog_path)
    resources = _select_resources(catalog, all_flag, list(resource_ids), list(filter_tags))

    if not resources:
        console.print("[yellow]未选择任何资源，请使用 --all、--id 或 --tag 指定目标[/yellow]")
        sys.exit(1)

    updates = {}
    if name:
        updates["name"] = name
    if source:
        updates["source"] = source
    if update_frequency:
        updates["update_frequency"] = update_frequency
    if authorization_scope:
        updates["authorization_scope"] = authorization_scope
    if contact_name:
        updates["contact_name"] = contact_name
    if contact_email:
        updates["contact_email"] = contact_email
    if description:
        updates["description"] = description

    parsed_custom = {}
    for cf in custom_fields:
        if "=" in cf:
            k, v = cf.split("=", 1)
            parsed_custom[k.strip()] = v.strip()

    for r in resources:
        for key, value in updates.items():
            setattr(r, key, value)
        if parsed_custom:
            r.custom_fields.update(parsed_custom)
        r.touch()

    catalog._touch()
    _save_catalog(catalog, catalog_path)
    console.print(f"[green]已更新 {len(resources)} 个资源的元信息[/green]")


# ============================================================
# tag 命令
# ============================================================
@main.command(help="批量为资源添加/移除行业标签")
@click.option("-c", "--catalog", "catalog_path", default=DEFAULT_CATALOG_FILE,
              help="目录清单文件路径")
@click.option("-a", "--all", "all_flag", is_flag=True, help="对所有资源执行操作")
@click.option("--id", "resource_ids", multiple=True, help="指定资源 ID（可多次指定）")
@click.option("--filter-tag", "filter_tags", multiple=True,
              help="按已有标签筛选目标资源（可多次指定）")
@click.option("--add", "add_tags", multiple=True, help="要添加的标签（可多次指定）")
@click.option("--remove", "remove_tags", multiple=True, help="要移除的标签（可多次指定）")
@click.option("--clear", is_flag=True, help="清空所有标签")
def tag(catalog_path, all_flag, resource_ids, filter_tags, add_tags, remove_tags, clear):
    catalog = _load_catalog(catalog_path)
    resources = _select_resources(catalog, all_flag, list(resource_ids), list(filter_tags))

    if not resources:
        console.print("[yellow]未选择任何资源，请使用 --all、--id 或 --filter-tag 指定目标[/yellow]")
        sys.exit(1)

    for r in resources:
        if clear:
            r.tags = []
        if remove_tags:
            r.tags = [t for t in r.tags if t not in remove_tags]
        if add_tags:
            for t in add_tags:
                if t not in r.tags:
                    r.tags.append(t)
        r.touch()

    catalog._touch()
    _save_catalog(catalog, catalog_path)

    ops = []
    if add_tags:
        ops.append(f"添加标签 {list(add_tags)}")
    if remove_tags:
        ops.append(f"移除标签 {list(remove_tags)}")
    if clear:
        ops.append("清空标签")
    console.print(f"[green]已对 {len(resources)} 个资源执行: {', '.join(ops)}[/green]")


# ============================================================
# check 命令
# ============================================================
@main.command(help="检查资源元信息：缺失字段、敏感描述等")
@click.option("-c", "--catalog", "catalog_path", default=DEFAULT_CATALOG_FILE,
              help="目录清单文件路径")
@click.option("--id", "resource_ids", multiple=True, help="只检查指定资源 ID")
@click.option("--only-errors", is_flag=True, help="只显示有错误的资源")
@click.option("--strict", is_flag=True, help="严格模式，存在错误则退出码为 1")
def check(catalog_path, resource_ids, only_errors, strict):
    catalog = _load_catalog(catalog_path)

    if resource_ids:
        resources = []
        for rid in resource_ids:
            r = catalog.get_resource(rid)
            if r:
                resources.append(r)
    else:
        resources = catalog.resources

    results = []
    for r in resources:
        from .checker import check_resource
        results.append(check_resource(r))

    if only_errors:
        results = [r for r in results if r.has_errors or r.warnings]

    _print_check_results(results)

    total = len(results)
    errors = sum(1 for r in results if r.missing_fields)
    warnings = sum(1 for r in results if r.sensitive_hits or r.warnings)
    oks = sum(1 for r in results if r.severity == "ok")

    console.print()
    console.print(f"总计: {total} | 通过: [green]{oks}[/green] | "
                  f"缺失字段: [red]{errors}[/red] | 警告: [yellow]{warnings}[/yellow]")

    if strict and has_errors(results):
        sys.exit(1)


# ============================================================
# publish 命令
# ============================================================
@main.command(help="按条件过滤待发布资源，并标记为已发布")
@click.option("-c", "--catalog", "catalog_path", default=DEFAULT_CATALOG_FILE,
              help="目录清单文件路径")
@click.option("--list", "list_flag", is_flag=True,
              help="列出待发布资源（默认行为）")
@click.option("--do", "do_publish", is_flag=True,
              help="执行发布操作，将符合条件的资源标记为已发布")
@click.option("-a", "--all-ready", is_flag=True,
              help="发布所有字段完整且未发布的资源")
@click.option("--id", "resource_ids", multiple=True, help="发布指定资源 ID")
@click.option("--tag", "filter_tags", multiple=True, help="按标签筛选发布")
@click.option("--scope", "authorization_scope",
              type=click.Choice(AUTHORIZATION_SCOPES),
              help="按授权范围筛选")
@click.option("--frequency", "update_frequency",
              type=click.Choice(UPDATE_FREQUENCIES),
              help="按更新频率筛选")
@click.option("--source", help="按数据来源筛选")
def publish(catalog_path, list_flag, do_publish, all_ready, resource_ids,
            filter_tags, authorization_scope, update_frequency, source):
    catalog = _load_catalog(catalog_path)

    if all_ready:
        targets = get_pending_publish(catalog)
    elif resource_ids or filter_tags or authorization_scope or update_frequency or source:
        targets = filter_resources(
            catalog,
            published=False,
            tags=list(filter_tags) if filter_tags else None,
            authorization_scope=authorization_scope,
            update_frequency=update_frequency,
            source=source,
        )
        if resource_ids:
            id_set = set(resource_ids)
            targets = [r for r in targets if r.id in id_set]
    else:
        targets = get_pending_publish(catalog)
        console.print("[cyan]显示待发布资源（字段完整且未发布）:[/cyan]")

    if not targets:
        console.print("[yellow]没有符合条件的资源[/yellow]")
        return

    if do_publish:
        mark_published(catalog, resources=targets)
        _save_catalog(catalog, catalog_path)
        console.print(f"[green]已发布 {len(targets)} 个资源[/green]")

    _print_resource_table(targets, show_publish_status=True)


# ============================================================
# export 命令
# ============================================================
@main.command(help="导出平台导入文件，并可输出变更对比报告")
@click.option("-c", "--catalog", "catalog_path", default=DEFAULT_CATALOG_FILE,
              help="目录清单文件路径")
@click.option("-f", "--format", "fmt", default="json",
              type=click.Choice(["json", "csv"]),
              help="导出格式 (json/csv，默认 json)")
@click.option("-o", "--output", "output_path", required=True,
              help="输出文件路径")
@click.option("--only-published", is_flag=True, help="只导出已发布资源")
@click.option("--tag", "filter_tags", multiple=True, help="按标签筛选导出")
@click.option("--scope", "authorization_scope",
              type=click.Choice(AUTHORIZATION_SCOPES),
              help="按授权范围筛选导出")
@click.option("--diff", "diff_path", type=click.Path(exists=True, dir_okay=False),
              help="与之前的目录文件对比，生成变更对比报告")
@click.option("--diff-output", "diff_output",
              help="变更对比报告输出路径（默认输出到终端）")
def export_cmd(catalog_path, fmt, output_path, only_published, filter_tags,
               authorization_scope, diff_path, diff_output):
    catalog = _load_catalog(catalog_path)

    resources = filter_resources(
        catalog,
        published=True if only_published else None,
        tags=list(filter_tags) if filter_tags else None,
        authorization_scope=authorization_scope,
    )

    if fmt == "json":
        content = to_platform_json(catalog, resources)
    else:
        content = to_platform_csv(catalog, resources)

    save_export(content, output_path)
    console.print(f"[green]已导出 {len(resources)} 个资源到: {output_path}[/green]")

    if diff_path:
        previous = _load_catalog(diff_path)
        report = generate_diff_report(catalog, previous)
        if diff_output:
            save_export(report, diff_output)
            console.print(f"[blue]变更对比报告已保存至: {diff_output}[/blue]")
        else:
            console.print()
            console.print(Panel(report, title="变更对比", border_style="cyan"))


main.add_command(export_cmd, name="export")


# ============================================================
# show 命令 - 查看资源完整元信息
# ============================================================
@main.command(help="查看指定资源的完整元信息摘要")
@click.argument("resource_id")
@click.option("-c", "--catalog", "catalog_path", default=DEFAULT_CATALOG_FILE,
              help="目录清单文件路径")
def show(resource_id, catalog_path):
    catalog = _load_catalog(catalog_path)
    resource = catalog.get_resource(resource_id)
    if not resource:
        console.print(f"[red]未找到资源 ID: {resource_id}[/red]")
        sys.exit(1)
    console.print(Panel(resource.summary(), title=f"资源: {resource.name or resource.file_name}",
                        border_style="blue"))


# ============================================================
# ls 命令 - 简洁列出所有资源
# ============================================================
@main.command("list", help="列出目录中的所有资源")
@click.option("-c", "--catalog", "catalog_path", default=DEFAULT_CATALOG_FILE,
              help="目录清单文件路径")
@click.option("--tag", "filter_tags", multiple=True, help="按标签筛选")
@click.option("--published/--unpublished", default=None,
              help="只显示已发布/未发布资源")
def list_cmd(catalog_path, filter_tags, published):
    catalog = _load_catalog(catalog_path)
    resources = filter_resources(
        catalog,
        published=published,
        tags=list(filter_tags) if filter_tags else None,
    )
    if not resources:
        console.print("[yellow]没有符合条件的资源[/yellow]")
        return
    _print_resource_table(resources, show_publish_status=True)


# ============================================================
# 辅助输出函数
# ============================================================
def _print_resource_table(resources: List[Resource], limit: Optional[int] = None,
                          show_publish_status: bool = False) -> None:
    display = resources[:limit] if limit else resources
    table = Table(box=box.SIMPLE, header_style="bold magenta")
    table.add_column("ID (前8位)", style="cyan", no_wrap=True)
    table.add_column("文件名", style="white")
    table.add_column("资源名称", style="green")
    table.add_column("类型", style="yellow")
    table.add_column("大小", style="blue", justify="right")
    if show_publish_status:
        table.add_column("已发布", justify="center")
    table.add_column("标签", style="magenta")

    for r in display:
        row = [
            r.id[:8],
            r.file_name,
            r.name or "-",
            r.file_type,
            Resource._format_size(r.file_size),
        ]
        if show_publish_status:
            row.append("[green]✓[/green]" if r.published else "[red]✗[/red]")
        row.append(", ".join(r.tags) if r.tags else "-")
        table.add_row(*row)

    console.print(table)
    if limit and len(resources) > limit:
        console.print(f"[dim]... 还有 {len(resources) - limit} 个资源未显示[/dim]")


def _print_check_results(results) -> None:
    table = Table(box=box.SIMPLE, header_style="bold magenta")
    table.add_column("状态", justify="center")
    table.add_column("资源", style="white")
    table.add_column("缺失字段", style="red")
    table.add_column("敏感词", style="yellow")
    table.add_column("警告", style="blue")

    severity_icon = {
        "ok": "[green]✓[/green]",
        "info": "[blue]i[/blue]",
        "warning": "[yellow]![/yellow]",
        "error": "[red]✗[/red]",
    }

    for r in results:
        table.add_row(
            severity_icon.get(r.severity, "?"),
            r.resource_name,
            ", ".join(r.missing_fields) if r.missing_fields else "-",
            ", ".join(r.sensitive_hits) if r.sensitive_hits else "-",
            "; ".join(r.warnings) if r.warnings else "-",
        )

    console.print(table)


if __name__ == "__main__":
    main()
