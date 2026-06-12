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

from .models import Catalog, Resource, CheckResult, UPDATE_FREQUENCIES, AUTHORIZATION_SCOPES
from .scanner import scan_directory
from .checker import (
    check_catalog, check_resource, has_errors,
    export_check_report_json, export_check_report_csv,
)
from .publisher import filter_resources, mark_published, mark_unpublished, get_pending_publish, preview_publish
from .exporter import to_platform_json, to_platform_csv, generate_diff_report, save_export
from .importer import read_import_file, apply_import


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
@click.option("--from-file", "import_file",
              type=click.Path(exists=True, dir_okay=False),
              help="从 CSV/Excel 文件批量导入元信息")
@click.option("--match-by", "match_by", default="file_path",
              type=click.Choice(["file_path", "id"]),
              help="批量导入时的匹配方式 (默认: file_path)")
def describe(catalog_path, all_flag, resource_ids, filter_tags, name, source,
             update_frequency, authorization_scope, contact_name, contact_email,
             description, custom_fields, import_file, match_by):
    catalog = _load_catalog(catalog_path)

    if import_file:
        _describe_from_file(catalog, catalog_path, import_file, match_by)
        return

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


def _describe_from_file(catalog: Catalog, catalog_path: str, import_file: str, match_by: str) -> None:
    console.print(f"[cyan]从文件批量导入元信息:[/cyan] {import_file}")
    console.print(f"[cyan]匹配方式:[/cyan] {match_by}")

    try:
        rows, warnings = read_import_file(import_file)
    except Exception as e:
        console.print(f"[red]读取导入文件失败: {e}[/red]")
        sys.exit(1)

    if warnings:
        for w in warnings:
            console.print(f"[yellow]{w}[/yellow]")

    if not rows:
        console.print("[yellow]导入文件中没有有效数据行[/yellow]")
        return

    console.print(f"[blue]读取到 {len(rows)} 行数据[/blue]")

    result = apply_import(catalog, rows, match_by=match_by)

    if result["matched"] > 0:
        _save_catalog(catalog, catalog_path)
        console.print(f"[green]成功匹配并更新 {result['matched']} 个资源[/green]")
        if result["updated_fields"]:
            console.print("[blue]更新字段统计:[/blue]")
            for field, count in result["updated_fields"].items():
                console.print(f"  {field}: {count} 个资源")
    else:
        console.print("[yellow]未匹配到任何资源，请检查匹配键是否正确[/yellow]")

    if result["unmatched"] > 0:
        console.print(f"[yellow]{result['unmatched']} 行数据未匹配到资源[/yellow]")
        for row in result["unmatched_rows"][:5]:
            key = row.get("resource_id") or row.get("file_path") or "?"
            console.print(f"  未匹配: {key}")
        if len(result["unmatched_rows"]) > 5:
            console.print(f"  ... 还有 {len(result['unmatched_rows']) - 5} 行未显示")


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
@main.command(help="检查资源元信息：缺失字段、敏感描述等，可导出审核报告")
@click.option("-c", "--catalog", "catalog_path", default=DEFAULT_CATALOG_FILE,
              help="目录清单文件路径")
@click.option("--id", "resource_ids", multiple=True, help="只检查指定资源 ID")
@click.option("--only-errors", is_flag=True, help="只显示有错误的资源")
@click.option("--strict", is_flag=True, help="严格模式，存在错误则退出码为 1")
@click.option("--report", "report_path",
              help="导出审核报告文件路径（根据扩展名自动选 JSON/CSV）")
@click.option("--report-format", "report_format",
              type=click.Choice(["json", "csv"]),
              help="审核报告格式（默认根据文件扩展名自动判断）")
def check(catalog_path, resource_ids, only_errors, strict, report_path, report_format):
    catalog = _load_catalog(catalog_path)

    if resource_ids:
        resources = []
        for rid in resource_ids:
            r = catalog.get_resource(rid)
            if r:
                resources.append(r)
    else:
        resources = catalog.resources

    results = [check_resource(r) for r in resources]

    if only_errors:
        results = [r for r in results if r.has_errors or r.warnings or r.issues]

    _print_check_results(results)

    total = len(results)
    summary = {"critical": 0, "error": 0, "warning": 0, "info": 0, "ok": 0}
    for r in results:
        summary[r.severity] = summary.get(r.severity, 0) + 1

    console.print()
    console.print(
        f"总计: {total} | "
        f"致命: [magenta]{summary['critical']}[/magenta] | "
        f"错误: [red]{summary['error']}[/red] | "
        f"警告: [yellow]{summary['warning']}[/yellow] | "
        f"信息: [blue]{summary['info']}[/blue] | "
        f"通过: [green]{summary['ok']}[/green]"
    )

    if report_path:
        fmt = report_format
        if not fmt:
            ext = Path(report_path).suffix.lower()
            fmt = "csv" if ext == ".csv" else "json"

        if fmt == "csv":
            content = export_check_report_csv(results)
        else:
            content = export_check_report_json(results, catalog)

        save_export(content, report_path)
        console.print(f"[green]审核报告已导出至: {report_path}[/green]")

    if strict and has_errors(results):
        sys.exit(1)


# ============================================================
# publish 命令
# ============================================================
@main.command(help="按条件过滤待发布资源，支持预演、发布和撤回")
@click.option("-c", "--catalog", "catalog_path", default=DEFAULT_CATALOG_FILE,
              help="目录清单文件路径")
@click.option("--dry-run", is_flag=True,
              help="发布预演：查看所有待发布资源及其通过/不通过原因，不实际发布")
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
@click.option("--unpublish", is_flag=True,
              help="撤回：将已发布资源恢复为草稿状态（配合 --id 或 --tag 指定目标）")
def publish(catalog_path, dry_run, do_publish, all_ready, resource_ids,
            filter_tags, authorization_scope, update_frequency, source, unpublish):
    catalog = _load_catalog(catalog_path)

    if unpublish:
        _handle_unpublish(catalog, catalog_path, list(resource_ids), list(filter_tags))
        return

    if dry_run:
        _handle_dry_run(catalog)
        return

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


def _handle_dry_run(catalog: Catalog) -> None:
    console.print("[cyan bold]发布预演[/cyan bold]")
    preview = preview_publish(catalog)

    can_publish = [p for p in preview if p["can_publish"]]
    blocked = [p for p in preview if not p["can_publish"]]

    console.print()
    if can_publish:
        console.print(f"[green]可发布 ({len(can_publish)} 个):[/green]")
        _print_resource_table([p["resource"] for p in can_publish], show_publish_status=True)

    if blocked:
        console.print()
        console.print(f"[red]不可发布 ({len(blocked)} 个):[/red]")
        table = Table(box=box.SIMPLE, header_style="bold magenta")
        table.add_column("资源", style="white")
        table.add_column("文件名", style="cyan")
        table.add_column("不通过原因", style="red")
        for p in blocked:
            r = p["resource"]
            reasons = "\n".join(p["block_reasons"])
            table.add_row(r.name or r.file_name, r.file_name, reasons)
        console.print(table)

    console.print()
    console.print(f"预演结果: 可发布 [green]{len(can_publish)}[/green] | 阻塞 [red]{len(blocked)}[/red]")
    console.print("[dim]确认发布请使用 --do 参数[/dim]")


def _handle_unpublish(catalog: Catalog, catalog_path: str,
                      resource_ids: List[str], filter_tags: List[str]) -> None:
    if not resource_ids and not filter_tags:
        console.print("[red]撤回操作必须指定 --id 或 --tag 来选择目标资源[/red]")
        sys.exit(1)

    target_ids = set(resource_ids)
    targets = []

    for r in catalog.resources:
        if r.id in target_ids and r.published:
            targets.append(r)
        elif filter_tags and r.published and any(t in r.tags for t in filter_tags):
            targets.append(r)

    if not targets:
        console.print("[yellow]没有符合条件的已发布资源可撤回[/yellow]")
        return

    console.print(f"[cyan]将撤回以下 {len(targets)} 个资源:[/cyan]")
    _print_resource_table(targets, show_publish_status=True)

    mark_unpublished(catalog, resource_ids=resource_ids, tags=filter_tags if filter_tags else None)
    _save_catalog(catalog, catalog_path)
    console.print(f"[green]已撤回 {len(targets)} 个资源到草稿状态[/green]")


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

    has_filters = only_published or filter_tags or authorization_scope

    if has_filters and not resources:
        console.print("[yellow]筛选条件没有匹配到任何资源[/yellow]")
        console.print("[yellow]已生成空资源结果文件，未匹配的资源不会被包含在内[/yellow]")

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
# show 命令
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
# list 命令
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


def _print_check_results(results: List[CheckResult]) -> None:
    severity_icon = {
        "critical": "[magenta bold]✗✗[/magenta bold]",
        "error": "[red]✗[/red]",
        "warning": "[yellow]![/yellow]",
        "info": "[blue]i[/blue]",
        "ok": "[green]✓[/green]",
    }

    severity_label = {
        "critical": "[magenta]致命[/magenta]",
        "error": "[red]错误[/red]",
        "warning": "[yellow]警告[/yellow]",
        "info": "[blue]信息[/blue]",
        "ok": "[green]通过[/green]",
    }

    table = Table(box=box.SIMPLE, header_style="bold magenta")
    table.add_column("状态", justify="center")
    table.add_column("等级", justify="center")
    table.add_column("资源", style="white")
    table.add_column("问题分类", style="cyan")
    table.add_column("详情", style="white")

    for r in results:
        if not r.issues:
            table.add_row(
                severity_icon.get(r.severity, "?"),
                severity_label.get(r.severity, "?"),
                r.resource_name,
                "-",
                "通过审核",
            )
        else:
            for i, issue in enumerate(r.issues):
                icon = severity_icon.get(issue.level, "?")
                label = severity_label.get(issue.level, "?")
                name = r.resource_name if i == 0 else ""
                table.add_row(
                    icon,
                    label,
                    name,
                    issue.category,
                    issue.message,
                )

    console.print(table)


if __name__ == "__main__":
    main()
