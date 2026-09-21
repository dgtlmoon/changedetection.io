from __future__ import annotations

import os
import queue
import threading
import uuid
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .credentials import CredentialError, protect_token, unprotect_token
from .github_api import GitHubAPIError, GitHubClient
from .models import (
    ConfigError,
    DEFAULT_CONFIG_PATTERNS,
    RELEASE_ASSET_PLATFORM_LABELS,
    RESOURCE_LABELS,
    CheckResult,
    MonitorConfig,
    parse_github_repo_url,
    parse_patterns,
)
from .monitor import GitHubMonitor
from .scheduler import MonitorScheduler
from .storage import AppStorage


GITHUB_TOKEN_CREATION_URL = "https://github.com/settings/personal-access-tokens/new"


class GitHubMonitorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("GitHub 仓库更新监控与下载")
        self.root.geometry("1180x820")
        self.root.minsize(980, 700)
        self.storage = AppStorage()
        self.jobs: list[MonitorConfig] = []
        self.editing_job_id: str | None = None
        self.results: queue.Queue[CheckResult] = queue.Queue()
        self.token_validation_results: queue.Queue[tuple[int, str, str]] = queue.Queue()
        self._token_check_generation = 0
        self._token_check_after: str | None = None
        self._token_settings_window: tk.Toplevel | None = None
        self.status_by_job: dict[str, str] = {}
        self.monitor = GitHubMonitor(self.storage)
        self.scheduler = MonitorScheduler(self.monitor, self.results.put)

        self.url_var = tk.StringVar()
        self.folder_var = tk.StringVar()
        self.interval_var = tk.StringVar(value="15")
        self.token_var = tk.StringVar()
        self.remember_token_var = tk.BooleanVar(value=True)
        self.token_status_var = tk.StringVar(value="未填写：公开仓库可用，但 API 额度较低")
        self.release_assets_var = tk.BooleanVar(value=True)
        self.release_source_var = tk.BooleanVar(value=True)
        self.release_platform_vars = {
            name: tk.BooleanVar(value=True) for name in RELEASE_ASSET_PLATFORM_LABELS
        }
        self.resource_vars = {name: tk.BooleanVar(value=True) for name in RESOURCE_LABELS}
        self.scheduler_status_var = tk.StringVar(value="监控未启动")

        self._build_ui()
        self.token_var.trace_add("write", self._token_changed)
        self._load_config()
        self._refresh_tree()
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.after(250, self._drain_results)
        if self.jobs:
            self._start_monitoring(log=False)

    def _build_ui(self) -> None:
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")

        outer = ttk.Frame(self.root, padding=12)
        outer.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        form = ttk.LabelFrame(outer, text="仓库监控设置", padding=10)
        form.grid(row=0, column=0, sticky="ew")
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="GitHub URL").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Entry(form, textvariable=self.url_var).grid(row=0, column=1, columnspan=5, sticky="ew", pady=3)

        ttk.Label(form, text="下载目录").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Entry(form, textvariable=self.folder_var).grid(row=1, column=1, columnspan=4, sticky="ew", pady=3)
        ttk.Button(form, text="选择…", command=self._choose_folder).grid(row=1, column=5, padx=(8, 0), pady=3)

        ttk.Label(form, text="检查间隔").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Spinbox(form, from_=1, to=10080, textvariable=self.interval_var, width=8).grid(row=2, column=1, sticky="w", pady=3)
        ttk.Label(form, text="分钟（无令牌时建议不少于 15 分钟）").grid(row=2, column=2, columnspan=4, sticky="w", pady=3)

        ttk.Label(form, text="监控内容").grid(row=3, column=0, sticky="nw", padx=(0, 8), pady=5)
        resources = ttk.Frame(form)
        resources.grid(row=3, column=1, columnspan=5, sticky="ew", pady=3)
        for index, (name, label) in enumerate(RESOURCE_LABELS.items()):
            ttk.Checkbutton(resources, text=label, variable=self.resource_vars[name]).grid(
                row=index // 4, column=index % 4, sticky="w", padx=(0, 20), pady=2
            )

        ttk.Label(form, text="配置规则").grid(row=4, column=0, sticky="nw", padx=(0, 8), pady=5)
        self.pattern_text = tk.Text(form, height=4, wrap="none", undo=True)
        self.pattern_text.grid(row=4, column=1, columnspan=5, sticky="ew", pady=3)
        self.pattern_text.insert("1.0", "\n".join(DEFAULT_CONFIG_PATTERNS))

        ttk.Label(form, text="Release 下载").grid(row=5, column=0, sticky="nw", padx=(0, 8), pady=5)
        release_options = ttk.Frame(form)
        release_options.grid(row=5, column=1, columnspan=5, sticky="w", pady=3)
        general_release_options = ttk.Frame(release_options)
        general_release_options.grid(row=0, column=0, columnspan=5, sticky="w")
        ttk.Checkbutton(
            general_release_options, text="下载 Release 附件", variable=self.release_assets_var
        ).pack(side="left", padx=(0, 18))
        ttk.Checkbutton(
            general_release_options, text="下载 Release 源码 ZIP", variable=self.release_source_var
        ).pack(side="left")
        ttk.Label(release_options, text="附件版本：").grid(row=1, column=0, sticky="w", pady=(4, 0))
        for index, (name, label) in enumerate(RELEASE_ASSET_PLATFORM_LABELS.items(), start=1):
            ttk.Checkbutton(
                release_options, text=label, variable=self.release_platform_vars[name]
            ).grid(row=1, column=index, sticky="w", padx=(0, 16), pady=(4, 0))

        ttk.Label(form, text="GitHub Token（PAT）").grid(row=6, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Label(form, textvariable=self.token_status_var, foreground="#555555", wraplength=780).grid(
            row=6, column=1, columnspan=4, sticky="w", pady=3
        )
        ttk.Button(form, text="Token 设置…", command=self._open_token_settings).grid(
            row=6, column=5, sticky="e", padx=(8, 0), pady=3
        )

        edit_buttons = ttk.Frame(form)
        edit_buttons.grid(row=7, column=0, columnspan=6, sticky="ew", pady=(8, 0))
        ttk.Button(edit_buttons, text="保存仓库", command=self._save_job).pack(side="left")
        ttk.Button(edit_buttons, text="新建", command=self._new_job).pack(side="left", padx=6)
        ttk.Button(edit_buttons, text="删除所选", command=self._delete_job).pack(side="left")
        ttk.Label(edit_buttons, text="首次检查会建立基线并下载每类最新内容。", foreground="#555555").pack(side="right")

        controls = ttk.Frame(outer)
        controls.grid(row=1, column=0, sticky="ew", pady=10)
        ttk.Button(controls, text="启动监控并立即检查所选", command=self._check_selected).pack(side="left")
        ttk.Button(controls, text="停止监控", command=self._stop_monitoring).pack(side="left", padx=6)
        ttk.Button(controls, text="打开下载目录", command=self._open_selected_folder).pack(side="left", padx=6)
        ttk.Label(controls, textvariable=self.scheduler_status_var).pack(side="right")

        body = ttk.Panedwindow(outer, orient="vertical")
        body.grid(row=2, column=0, sticky="nsew")
        jobs_frame = ttk.LabelFrame(body, text="监控仓库", padding=6)
        log_frame = ttk.LabelFrame(body, text="运行日志", padding=6)
        body.add(jobs_frame, weight=3)
        body.add(log_frame, weight=2)

        columns = ("repository", "resources", "interval", "folder", "status")
        self.tree = ttk.Treeview(jobs_frame, columns=columns, show="headings", selectmode="browse")
        widths = {"repository": 170, "resources": 300, "interval": 75, "folder": 330, "status": 180}
        labels = {"repository": "仓库", "resources": "监控内容", "interval": "间隔", "folder": "下载目录", "status": "状态"}
        for column in columns:
            self.tree.heading(column, text=labels[column])
            self.tree.column(column, width=widths[column], minwidth=60, anchor="w")
        scrollbar = ttk.Scrollbar(jobs_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._load_selected)

        self.log = tk.Text(log_frame, height=9, state="disabled", wrap="word")
        log_scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=log_scrollbar.set)
        self.log.pack(side="left", fill="both", expand=True)
        log_scrollbar.pack(side="right", fill="y")

    def _load_config(self) -> None:
        payload = self.storage.load_config()
        for value in payload.get("jobs") or []:
            try:
                self.jobs.append(MonitorConfig.from_dict(value))
            except (ConfigError, TypeError, ValueError) as exc:
                self._log(f"已跳过无效配置：{exc}")
        remembered = bool(payload.get("remember_token", True))
        self.remember_token_var.set(remembered)
        if remembered and payload.get("token_protected"):
            try:
                self.token_var.set(unprotect_token(str(payload["token_protected"])))
            except CredentialError as exc:
                self._log(f"无法读取已保存令牌：{exc}")

    def _open_token_settings(self) -> None:
        existing = self._token_settings_window
        if existing is not None:
            try:
                if existing.winfo_exists():
                    existing.deiconify()
                    existing.lift()
                    existing.focus_force()
                    return
            except tk.TclError:
                pass

        popup = tk.Toplevel(self.root)
        self._token_settings_window = popup
        popup.title("GitHub Token 设置")
        popup.geometry("700x390")
        popup.resizable(False, False)
        popup.transient(self.root)

        frame = ttk.Frame(popup, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="GitHub Personal Access Token（PAT）", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(
            frame,
            text=(
                "只需粘贴 GitHub 令牌，无需填写用户名或密码。程序会自动验证；验证成功后立即供监控使用。\n"
                "建议使用 fine-grained token，并仅为目标仓库授予所需内容的只读权限。"
            ),
            wraplength=650,
            justify="left",
        ).pack(anchor="w", pady=(8, 14))

        token_input_var = tk.StringVar(value=self.token_var.get())
        token_row = ttk.Frame(frame)
        token_row.pack(fill="x")
        token_entry = ttk.Entry(token_row, textvariable=token_input_var, show="●")
        token_entry.pack(side="left", fill="x", expand=True)
        visible_var = tk.BooleanVar(value=False)

        def toggle_visibility() -> None:
            token_entry.configure(show="" if visible_var.get() else "●")

        ttk.Checkbutton(
            token_row,
            text="显示",
            variable=visible_var,
            command=toggle_visibility,
        ).pack(side="left", padx=(10, 0))
        ttk.Checkbutton(
            frame,
            text="验证成功后使用 Windows DPAPI 自动安全保存",
            variable=self.remember_token_var,
        ).pack(anchor="w", pady=(12, 6))
        ttk.Label(frame, textvariable=self.token_status_var, foreground="#555555", wraplength=650).pack(
            anchor="w", pady=(2, 10)
        )
        ttk.Label(
            frame,
            text="需要 Discussions 或 Security alerts 时，请同时为令牌授予对应的只读权限。",
            foreground="#555555",
            wraplength=650,
        ).pack(anchor="w")

        def apply_token() -> None:
            token = token_input_var.get().strip()
            if not self._apply_token_from_settings(token):
                messagebox.showwarning("未填写令牌", "请粘贴 GitHub Personal Access Token。", parent=popup)
                token_entry.focus_set()
                return
            token_input_var.set(token)
            self._log("已提交 GitHub Token，正在自动验证。")

        def clear_token() -> None:
            if not self.token_var.get().strip() and not token_input_var.get().strip():
                return
            if not messagebox.askyesno("清除令牌", "清除当前 GitHub Token 及已保存的 DPAPI 密文？", parent=popup):
                return
            token_input_var.set("")
            self.token_var.set("")
            if self._persist_config():
                self.scheduler.update(self.jobs, "")
                self._log("GitHub Token 已清除；后续请求将使用未认证 API 额度。")
                messagebox.showinfo("令牌已清除", "已清除 GitHub Token。", parent=popup)

        def close_popup() -> None:
            if self._token_settings_window is popup:
                self._token_settings_window = None
            try:
                popup.grab_release()
            except tk.TclError:
                pass
            popup.destroy()

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", side="bottom", pady=(18, 0))
        ttk.Button(
            buttons,
            text="打开 GitHub 创建令牌页面",
            command=lambda: webbrowser.open(GITHUB_TOKEN_CREATION_URL),
        ).pack(side="left")
        ttk.Button(buttons, text="清除令牌", command=clear_token).pack(side="left", padx=8)
        ttk.Button(buttons, text="验证并应用", command=apply_token).pack(side="right")
        ttk.Button(buttons, text="关闭", command=close_popup).pack(side="right", padx=8)

        popup.protocol("WM_DELETE_WINDOW", close_popup)
        popup.grab_set()
        token_entry.focus_set()
        token_entry.selection_range(0, "end")

    def _apply_token_from_settings(self, value: str) -> bool:
        token = str(value or "").strip()
        if not token:
            return False
        self.token_var.set(token)
        return True

    def _token_changed(self, *_args) -> None:
        self._token_check_generation += 1
        generation = self._token_check_generation
        if self._token_check_after is not None:
            try:
                self.root.after_cancel(self._token_check_after)
            except tk.TclError:
                pass
            self._token_check_after = None
        token = self.token_var.get().strip()
        if not token:
            self.token_status_var.set("未填写：公开仓库可用，但 API 额度较低")
            return
        self.token_status_var.set("等待自动验证 GitHub Token…")
        self._token_check_after = self.root.after(700, lambda: self._begin_token_validation(generation, token))

    def _begin_token_validation(self, generation: int, token: str) -> None:
        self._token_check_after = None
        if generation != self._token_check_generation or token != self.token_var.get().strip():
            return
        self.token_status_var.set("正在验证 GitHub Token…")

        def worker() -> None:
            try:
                client = GitHubClient(token, timeout=20)
                user = client.get_authenticated_user()
                login = str(user.get("login") or "未知账号")
                remaining = client.minimum_rate_remaining
                suffix = f"，API 剩余 {remaining}" if remaining is not None else ""
                status, message = "ok", f"令牌有效：{login}{suffix}"
            except GitHubAPIError as exc:
                status, message = "error", f"令牌验证失败：{exc}"
            self.token_validation_results.put((generation, status, message))

        threading.Thread(target=worker, name="github-token-validation", daemon=True).start()

    def _persist_config(self) -> bool:
        protected = ""
        if self.remember_token_var.get() and self.token_var.get().strip():
            try:
                protected = protect_token(self.token_var.get().strip())
            except CredentialError as exc:
                messagebox.showerror("无法保存令牌", str(exc), parent=self.root)
                return False
        self.storage.save_config(
            {
                "jobs": [job.to_dict() for job in self.jobs],
                "remember_token": bool(self.remember_token_var.get()),
                "token_protected": protected,
            }
        )
        return True

    def _choose_folder(self) -> None:
        initial = self.folder_var.get().strip() or str(Path.home() / "Downloads")
        selected = filedialog.askdirectory(parent=self.root, initialdir=initial, mustexist=True)
        if selected:
            self.folder_var.set(selected)

    def _form_config(self) -> MonitorConfig:
        owner, repo, canonical = parse_github_repo_url(self.url_var.get())
        resources = [name for name, variable in self.resource_vars.items() if variable.get()]
        try:
            interval = int(self.interval_var.get().strip())
        except ValueError as exc:
            raise ConfigError("检查间隔必须是整数分钟。") from exc
        download_dir = str(Path(self.folder_var.get().strip()).expanduser().resolve()) if self.folder_var.get().strip() else ""
        config = MonitorConfig(
            repo_url=canonical,
            owner=owner,
            repo=repo,
            download_dir=download_dir,
            interval_minutes=interval,
            resources=resources,
            config_patterns=parse_patterns(self.pattern_text.get("1.0", "end")),
            download_release_assets=bool(self.release_assets_var.get()),
            download_release_source=bool(self.release_source_var.get()),
            release_asset_platforms=[
                name for name, variable in self.release_platform_vars.items() if variable.get()
            ],
            job_id=self.editing_job_id or uuid.uuid4().hex,
        )
        config.validate()
        return config

    def _commit_form_job(self, *, log: bool = True) -> MonitorConfig | None:
        try:
            config = self._form_config()
        except ConfigError as exc:
            messagebox.showerror("设置无效", str(exc), parent=self.root)
            return None
        duplicate = next((job for job in self.jobs if job.display_name.lower() == config.display_name.lower() and job.job_id != config.job_id), None)
        if duplicate:
            messagebox.showerror("仓库已存在", f"{config.display_name} 已在监控列表中。", parent=self.root)
            return None
        index = next((i for i, job in enumerate(self.jobs) if job.job_id == config.job_id), None)
        repository_changed = index is not None and self.jobs[index].display_name.lower() != config.display_name.lower()
        previous_jobs = list(self.jobs)
        previous_editing_job_id = self.editing_job_id
        if index is None:
            self.jobs.append(config)
        else:
            self.jobs[index] = config
        self.editing_job_id = config.job_id
        if not self._persist_config():
            self.jobs = previous_jobs
            self.editing_job_id = previous_editing_job_id
            return None
        if repository_changed:
            self.storage.delete_job_state(config.job_id)
        self._refresh_tree(select_id=config.job_id)
        self.scheduler.update(self.jobs, self.token_var.get().strip())
        if log:
            self._log(f"已保存 {config.display_name}；下一次检查将使用当前设置。")
        return config

    def _save_job(self) -> None:
        known_job_ids = {job.job_id for job in self.jobs}
        config = self._commit_form_job()
        if config is None or config.job_id in known_job_ids:
            return
        if not self.scheduler.running:
            self._start_monitoring(log=False)
        self.status_by_job[config.job_id] = "首次测试中…"
        self._refresh_tree(select_id=config.job_id)
        self._log(f"已自动开始首次测试 {config.display_name}；成功后会下载各勾选项的最新内容。")

    def _new_job(self) -> None:
        self.editing_job_id = None
        self.url_var.set("")
        self.folder_var.set("")
        self.interval_var.set("15")
        for variable in self.resource_vars.values():
            variable.set(True)
        self.pattern_text.delete("1.0", "end")
        self.pattern_text.insert("1.0", "\n".join(DEFAULT_CONFIG_PATTERNS))
        self.release_assets_var.set(True)
        self.release_source_var.set(True)
        for variable in self.release_platform_vars.values():
            variable.set(True)
        self.tree.selection_remove(self.tree.selection())

    def _delete_job(self) -> None:
        job = self._selected_job()
        if not job:
            messagebox.showinfo("未选择仓库", "请先选择要删除的仓库。", parent=self.root)
            return
        if not messagebox.askyesno("删除监控", f"停止并删除 {job.display_name} 的监控设置？\n已下载文件不会删除。", parent=self.root):
            return
        self.jobs = [value for value in self.jobs if value.job_id != job.job_id]
        self.storage.delete_job_state(job.job_id)
        self.editing_job_id = None
        self._persist_config()
        self.scheduler.update(self.jobs, self.token_var.get().strip())
        self._refresh_tree()
        self._new_job()
        self._log(f"已删除 {job.display_name} 的监控设置；下载文件已保留。")

    def _refresh_tree(self, select_id: str | None = None) -> None:
        if select_id is None:
            current = self.tree.selection()
            select_id = current[0] if current else None
        for item in self.tree.get_children():
            self.tree.delete(item)
        for job in self.jobs:
            labels = "、".join(RESOURCE_LABELS[name] for name in job.resources)
            self.tree.insert(
                "",
                "end",
                iid=job.job_id,
                values=(job.display_name, labels, f"{job.interval_minutes} 分钟", job.download_dir, self.status_by_job.get(job.job_id, "等待检查")),
            )
        if select_id and self.tree.exists(select_id):
            self.tree.selection_set(select_id)
            self.tree.focus(select_id)

    def _selected_job(self) -> MonitorConfig | None:
        selected = self.tree.selection()
        if not selected:
            return None
        return next((job for job in self.jobs if job.job_id == selected[0]), None)

    def _load_selected(self, _event=None) -> None:
        job = self._selected_job()
        if not job:
            return
        self.editing_job_id = job.job_id
        self.url_var.set(job.repo_url)
        self.folder_var.set(job.download_dir)
        self.interval_var.set(str(job.interval_minutes))
        for name, variable in self.resource_vars.items():
            variable.set(name in job.resources)
        self.pattern_text.delete("1.0", "end")
        self.pattern_text.insert("1.0", "\n".join(job.config_patterns))
        self.release_assets_var.set(job.download_release_assets)
        self.release_source_var.set(job.download_release_source)
        for name, variable in self.release_platform_vars.items():
            variable.set(name in job.release_asset_platforms)

    def _start_monitoring(self, log: bool = True) -> None:
        if not self.jobs:
            if log:
                messagebox.showinfo("没有监控仓库", "请先添加并保存一个 GitHub 仓库。", parent=self.root)
            return
        if not self._persist_config():
            return
        self.scheduler.start(self.jobs, self.token_var.get().strip())
        self.scheduler_status_var.set("监控运行中")
        if log:
            self._log("监控已启动；将立即检查各仓库。")

    def _stop_monitoring(self) -> None:
        self.scheduler.stop()
        self.scheduler_status_var.set("监控已停止")
        self._log("监控已停止。")

    def _check_selected(self) -> None:
        job = self._selected_job()
        if not job:
            messagebox.showinfo("未选择仓库", "请先选择一个仓库。", parent=self.root)
            return
        if self.editing_job_id == job.job_id:
            current = self._commit_form_job(log=False)
            if current is None:
                return
            job = current
        if not self.scheduler.running:
            self._start_monitoring(log=False)
        self.scheduler.update(self.jobs, self.token_var.get().strip())
        self.scheduler.check_now(job.job_id)
        self.status_by_job[job.job_id] = "正在检查…"
        self._refresh_tree(select_id=job.job_id)
        self._log(f"监控运行中；已保存当前设置并请求立即检查 {job.display_name}。")

    def _open_selected_folder(self) -> None:
        job = self._selected_job()
        if not job:
            messagebox.showinfo("未选择仓库", "请先选择一个仓库。", parent=self.root)
            return
        path = Path(job.download_dir).expanduser() / job.repository_folder_name
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(path)  # type: ignore[attr-defined]

    def _drain_results(self) -> None:
        try:
            while True:
                generation, validation_status, message = self.token_validation_results.get_nowait()
                if generation == self._token_check_generation:
                    self.token_status_var.set(message)
                    if validation_status == "ok" and self._persist_config():
                        self.scheduler.update(self.jobs, self.token_var.get().strip())
                        selected = self._selected_job()
                        if self.scheduler.running and selected:
                            self.scheduler.check_now(selected.job_id)
                        if self.remember_token_var.get():
                            self._log("GitHub Token 已验证并通过 Windows DPAPI 安全保存；运行中的监控已自动采用该令牌。")
                        else:
                            self._log("GitHub Token 已验证并应用于本次运行；自动安全保存未启用。")
        except queue.Empty:
            pass
        try:
            while True:
                result = self.results.get_nowait()
                self._handle_result(result)
        except queue.Empty:
            pass
        self.root.after(250, self._drain_results)

    def _handle_result(self, result: CheckResult) -> None:
        pieces = [f"{result.checked_at} 检查完成"]
        if result.events:
            pieces.append(f"{len(result.events)} 个变化")
        if result.initialized_resources:
            labels = "、".join(RESOURCE_LABELS[name] for name in result.initialized_resources)
            pieces.append(f"已建立基线：{labels}")
        if result.initial_downloaded_paths:
            pieces.append(f"首次下载 {len(result.initial_downloaded_paths)} 个文件")
        if result.warnings:
            pieces.append(f"{len(result.warnings)} 个警告")
        if result.rate_limited:
            pieces.append("本轮已限流")
        elif result.rate_remaining is not None:
            pieces.append(f"API 剩余 {result.rate_remaining}")
        status = "；".join(pieces)
        self.status_by_job[result.job_id] = status
        self._refresh_tree()
        self._log(f"{result.repository}：{status}")
        for warning in result.warnings:
            self._log(f"  警告：{warning}")
        if result.initialized_resources:
            self._show_initial_check_popup(result)
        if result.events:
            self._show_change_popup(result)

    def _show_initial_check_popup(self, result: CheckResult) -> None:
        labels = "、".join(RESOURCE_LABELS[name] for name in result.initialized_resources)
        message = (
            f"{result.repository} 首次测试完成。\n\n"
            f"已建立基线：{labels}\n"
            f"已下载：{len(result.initial_downloaded_paths)} 个文件"
        )
        if result.warnings:
            message += f"\n警告：{len(result.warnings)} 个（详情见运行日志）"
        messagebox.showinfo("首次检查完成", message, parent=self.root)

    def _show_change_popup(self, result: CheckResult) -> None:
        self.root.bell()
        popup = tk.Toplevel(self.root)
        popup.title("GitHub 仓库有更新")
        popup.geometry("660x380")
        popup.transient(self.root)
        popup.attributes("-topmost", True)
        frame = ttk.Frame(popup, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=f"{result.repository} 检测到 {len(result.events)} 个实际内容变化", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        text = tk.Text(frame, height=13, wrap="word")
        text.pack(fill="both", expand=True, pady=10)
        for event in result.events:
            text.insert("end", f"• {event.title}\n")
            if event.downloaded_paths:
                text.insert("end", f"  已下载 {len(event.downloaded_paths)} 个文件\n")
        text.configure(state="disabled")
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")
        job = next((value for value in self.jobs if value.job_id == result.job_id), None)
        if job:
            ttk.Button(buttons, text="打开下载目录", command=lambda: self._open_path(Path(job.download_dir) / job.repository_folder_name)).pack(side="left")
        first_url = next((event.url for event in result.events if event.url), "")
        if first_url:
            ttk.Button(buttons, text="打开 GitHub 页面", command=lambda: webbrowser.open(first_url)).pack(side="left", padx=6)
        ttk.Button(buttons, text="关闭", command=popup.destroy).pack(side="right")
        popup.after(2000, lambda: popup.winfo_exists() and popup.attributes("-topmost", False))

    @staticmethod
    def _open_path(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(path)  # type: ignore[attr-defined]

    def _log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _close(self) -> None:
        self.scheduler.stop(timeout=3.0)
        self.root.destroy()


def run_app(exit_after_ms: int | None = None, *, open_token_settings: bool = False) -> None:
    root = tk.Tk()
    application = GitHubMonitorApp(root)
    if open_token_settings:
        root.after(100, application._open_token_settings)
    if exit_after_ms is not None:
        root.after(exit_after_ms, application._close)
    root.mainloop()
