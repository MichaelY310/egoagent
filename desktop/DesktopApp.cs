using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Net;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace EgoAgentDesktop
{
    internal static class Program
    {
        [DllImport("user32.dll")] private static extern bool SetForegroundWindow(IntPtr handle);
        [DllImport("user32.dll")] private static extern bool ShowWindow(IntPtr handle, int command);
        [DllImport("user32.dll")] private static extern bool IsIconic(IntPtr handle);
        [DllImport("user32.dll")] private static extern bool SetProcessDpiAwarenessContext(IntPtr value);
        [DllImport("shell32.dll", CharSet = CharSet.Unicode)] private static extern int SetCurrentProcessExplicitAppUserModelID(string id);
        private static Mutex instance;

        [STAThread]
        private static void Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            try { SetProcessDpiAwarenessContext(new IntPtr(-4)); } catch (EntryPointNotFoundException) { }
            SetCurrentProcessExplicitAppUserModelID("EgoAgent.Desktop");
            try
            {
                string configFile = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "desktop-config.json");
                var config = new JavaScriptSerializer().Deserialize<Dictionary<string, string>>(File.ReadAllText(configFile));
                string root = Path.GetFullPath(config["root"]);
                if (!File.Exists(Path.Combine(root, "start-all.py"))) throw new Exception("找不到 EgoAgent 仓库。移动仓库后请重新运行 desktop\\install.ps1。");
                string folder = null;
                bool newWindow = false;
                for (int i = 0; i < args.Length; i++)
                {
                    if (args[i] == "--new-window") newWindow = true;
                    else if (args[i] == "--folder" && i + 1 < args.Length) folder = Path.GetFullPath(args[++i]);
                    else throw new ArgumentException("参数只支持 --new-window 和 --folder <目录>");
                }
                if (folder != null && !Directory.Exists(folder)) throw new DirectoryNotFoundException("项目目录不存在：" + folder);
                bool created;
                instance = new Mutex(false, "Local\\EgoAgent.Desktop." + DesktopPolicy.RootKey(root), out created);
                if (!created && !newWindow && folder == null && ActivateExisting()) return;
                Application.Run(new DesktopContext(root, folder));
            }
            catch (Exception error)
            {
                MessageBox.Show(error.Message, "EgoAgent 无法启动", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
            finally { if (instance != null) instance.Dispose(); }
        }

        private static bool ActivateExisting()
        {
            string executable = Application.ExecutablePath;
            foreach (var process in Process.GetProcessesByName(Path.GetFileNameWithoutExtension(executable)))
            {
                try
                {
                    if (process.Id == Process.GetCurrentProcess().Id || process.MainWindowHandle == IntPtr.Zero
                        || !String.Equals(process.MainModule.FileName, executable, StringComparison.OrdinalIgnoreCase)) continue;
                    if (IsIconic(process.MainWindowHandle)) ShowWindow(process.MainWindowHandle, 9);
                    SetForegroundWindow(process.MainWindowHandle);
                    return true;
                }
                catch (Exception) { }
                finally { process.Dispose(); }
            }
            return false;
        }
    }

    internal sealed class DesktopContext : ApplicationContext
    {
        public readonly string Root;
        private readonly List<DesktopWindow> windows = new List<DesktopWindow>();
        public DesktopContext(string root, string folder) { Root = root; Open(folder, null); }
        public void Open(string folder, string url)
        {
            var window = new DesktopWindow(this, folder, url);
            windows.Add(window);
            window.FormClosed += delegate { windows.Remove(window); if (windows.Count == 0) ExitThread(); };
            window.Show();
        }
    }

    internal sealed class DesktopWindow : Form
    {
        private readonly DesktopContext context;
        private readonly string root;
        private readonly string statePath;
        private readonly DesktopState saved;
        private readonly Panel viewport = new Panel { Dock = DockStyle.Fill };
        private readonly Panel loading = new Panel { Dock = DockStyle.Fill, BackColor = Color.FromArgb(247, 248, 252) };
        private readonly Label status = new Label { AutoSize = false, Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleCenter, ForeColor = Color.FromArgb(52, 57, 70) };
        private readonly FlowLayoutPanel actions = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 72, FlowDirection = FlowDirection.LeftToRight, Padding = new Padding(24, 12, 0, 0) };
        private readonly ToolStripMenuItem recent = new ToolStripMenuItem("最近打开");
        private readonly ToolStripMenuItem connection = new ToolStripMenuItem("正在连接…") { Enabled = false };
        private readonly System.Windows.Forms.Timer healthTimer = new System.Windows.Forms.Timer { Interval = 15000 };
        private readonly HashSet<int> allowedPorts = new HashSet<int>();
        private WebView2 browser;
        private string origin;
        private string initialUrl;
        private bool starting;
        private bool closing;
        private bool checkingHealth;

        public DesktopWindow(DesktopContext owner, string folder, string url)
        {
            context = owner; root = owner.Root; initialUrl = url;
            statePath = Path.Combine(root, ".runtime", "desktop", "window.json");
            saved = DesktopState.Load(statePath, root);
            if (folder != null) saved.Workspace = folder;
            Text = "EgoAgent";
            Font = new Font("Microsoft YaHei UI", 9F);
            Icon = new Icon(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "egoagent.ico"));
            StartPosition = FormStartPosition.CenterScreen;
            MinimumSize = new Size(850, 580);
            Size = new Size(Math.Max(850, Math.Min(saved.Width, Screen.PrimaryScreen.WorkingArea.Width)), Math.Max(580, Math.Min(saved.Height, Screen.PrimaryScreen.WorkingArea.Height)));
            if (saved.Maximized) WindowState = FormWindowState.Maximized;
            AutoScaleMode = AutoScaleMode.Dpi;
            var menu = CreateMenu();
            var retry = new Button { Text = "重试连接", AutoSize = true, Height = 32 };
            retry.Click += async delegate { await StartAsync(); };
            var logs = new Button { Text = "打开运行日志", AutoSize = true, Height = 32 };
            logs.Click += delegate { OpenLogs(); };
            actions.Controls.Add(retry); actions.Controls.Add(logs);
            loading.Controls.Add(status); loading.Controls.Add(actions);
            viewport.Controls.Add(loading);
            Controls.Add(viewport); Controls.Add(menu); MainMenuStrip = menu;
            Shown += async delegate { await StartAsync(); };
            FormClosing += OnClosing;
            FormClosed += delegate { healthTimer.Dispose(); if (browser != null) browser.Dispose(); };
            healthTimer.Tick += async delegate { await CheckHealth(); };
        }

        private MenuStrip CreateMenu()
        {
            var menu = new MenuStrip { BackColor = Color.FromArgb(247, 248, 252), GripStyle = ToolStripGripStyle.Hidden };
            var file = new ToolStripMenuItem("文件");
            file.DropDownItems.Add("打开本机项目文件夹…", null, delegate { PickFolder(); });
            file.DropDownItems.Add(recent);
            file.DropDownItems.Add("新建窗口", null, delegate { context.Open(saved.Workspace, null); });
            file.DropDownItems.Add(new ToolStripSeparator());
            file.DropDownItems.Add("关闭窗口（后台任务继续）", null, delegate { Close(); });
            var view = new ToolStripMenuItem("视图");
            view.DropDownItems.Add("重新加载界面", null, delegate { Reload(); });
            view.DropDownItems.Add("放大", null, delegate { if (browser != null) browser.ZoomFactor = Math.Min(2, browser.ZoomFactor + 0.1); });
            view.DropDownItems.Add("缩小", null, delegate { if (browser != null) browser.ZoomFactor = Math.Max(0.5, browser.ZoomFactor - 0.1); });
            view.DropDownItems.Add("重置缩放", null, delegate { if (browser != null) browser.ZoomFactor = 1; });
            view.DropDownItems.Add("开发者工具", null, delegate { if (browser != null && browser.CoreWebView2 != null) browser.CoreWebView2.OpenDevToolsWindow(); });
            var service = new ToolStripMenuItem("服务");
            service.DropDownItems.Add(connection);
            service.DropDownItems.Add("检查 / 恢复连接", null, async delegate { await StartAsync(); });
            service.DropDownItems.Add("打开运行日志", null, delegate { OpenLogs(); });
            service.DropDownItems.Add(new ToolStripSeparator());
            service.DropDownItems.Add("停止桌面版启动的后台…", null, async delegate { await StopServices(); });
            var help = new ToolStripMenuItem("帮助");
            help.DropDownItems.Add("关于 EgoAgent 桌面版", null, delegate
            {
                MessageBox.Show(this, "EgoAgent Desktop\n\n独立 Windows 窗口 · 自动启动服务 · 最近项目\n\nIDE、Chat、Flow、Workbench 与浏览器版使用同一套后端。\n关闭窗口不会终止后台 Agent；停止后台请使用“服务”菜单。\n\n运行环境：Windows WebView2 + 现有 Python / Void。\n本版本依赖当前仓库，不是可拷走单个 exe 的独立安装包。", "关于 EgoAgent", MessageBoxButtons.OK, MessageBoxIcon.Information);
            });
            menu.Items.AddRange(new ToolStripItem[] { file, view, service, help });
            UpdateRecent();
            return menu;
        }

        private async Task StartAsync()
        {
            if (starting || closing) return;
            starting = true; actions.Visible = false; healthTimer.Stop();
            status.Text = "EgoAgent\n\n正在准备 IDE 和 Agent 服务…\n已有后台会自动复用，无需手动打开终端。";
            loading.Visible = true; loading.BringToFront();
            try
            {
                var result = await Bootstrap("");
                if (closing) return;
                origin = Convert.ToString(result["origin"]);
                allowedPorts.Clear(); allowedPorts.Add(new Uri(origin).Port); LoadRemotePorts();
                connection.Text = Convert.ToBoolean(result["started"]) ? "本机后台 · 桌面版已启动" : "本机后台 · 已连接";
                if (browser != null) { viewport.Controls.Remove(browser); browser.Dispose(); }
                browser = new WebView2 { Dock = DockStyle.Fill, DefaultBackgroundColor = Color.White };
                viewport.Controls.Add(browser); browser.SendToBack();
                string cache = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "EgoAgent", "WebView2", DesktopPolicy.RootKey(root));
                var environment = await CoreWebView2Environment.CreateAsync(null, cache, null);
                if (closing) return;
                await browser.EnsureCoreWebView2Async(environment);
                if (closing) return;
                ConfigureBrowser();
                await ResetOldClipboardDenials();
                string destination = initialUrl ?? DesktopPolicy.WorkspaceUrl(origin, saved.Workspace);
                initialUrl = null;
                if (!DesktopPolicy.IsInternal(destination, allowedPorts)) throw new Exception("拒绝在桌面窗口加载未知服务地址。");
                browser.CoreWebView2.Navigate(destination);
                healthTimer.Start();
            }
            catch (Exception error) { if (!closing) ShowError(error.Message); }
            finally { starting = false; }
        }

        private void ConfigureBrowser()
        {
            var core = browser.CoreWebView2;
            core.Settings.AreHostObjectsAllowed = false;
            core.Settings.IsWebMessageEnabled = false;
            core.Settings.IsStatusBarEnabled = false;
            core.Settings.IsPasswordAutosaveEnabled = false;
            core.Settings.IsGeneralAutofillEnabled = false;
            core.Settings.AreBrowserAcceleratorKeysEnabled = false;
            core.NavigationStarting += delegate(object sender, CoreWebView2NavigationStartingEventArgs args)
            {
                LoadRemotePorts();
                if (DesktopPolicy.IsInternal(args.Uri, allowedPorts)) return;
                args.Cancel = true;
                if (args.IsUserInitiated && DesktopPolicy.IsExternal(args.Uri)) OpenExternal(args.Uri);
            };
            core.NewWindowRequested += delegate(object sender, CoreWebView2NewWindowRequestedEventArgs args)
            {
                args.Handled = true;
                LoadRemotePorts();
                if (DesktopPolicy.IsInternal(args.Uri, allowedPorts)) context.Open(null, args.Uri);
                else if (args.IsUserInitiated && DesktopPolicy.IsExternal(args.Uri)) OpenExternal(args.Uri);
            };
            core.NavigationCompleted += delegate(object sender, CoreWebView2NavigationCompletedEventArgs args)
            {
                if (!args.IsSuccess) { ShowError("界面加载失败：" + args.WebErrorStatus + "。请点击重试连接。"); return; }
                loading.Visible = false; browser.BringToFront();
                RememberWorkspace(); browser.Focus();
            };
            core.SourceChanged += delegate { RememberWorkspace(); };
            core.DocumentTitleChanged += delegate
            {
                string title = core.DocumentTitle;
                Text = String.IsNullOrWhiteSpace(title) ? "EgoAgent" : title.Replace(" - Void", " - EgoAgent");
            };
            core.ProcessFailed += delegate(object sender, CoreWebView2ProcessFailedEventArgs args)
            {
                ShowError("界面进程异常（" + args.ProcessFailedKind + "）。后台任务未被停止，可以重试连接。");
            };
            core.WindowCloseRequested += delegate { Close(); };
            core.PermissionRequested += delegate(object sender, CoreWebView2PermissionRequestedEventArgs args)
            {
                // Desktop editing grants clipboard access to the active IDE and
                // its isolated Chat frames. Async extension reads can lose user
                // activation, so do not gate this on IsUserInitiated. Never grant
                // unrelated device permissions or access from another origin.
                // Re-evaluate on each request instead of granting a profile-wide
                // permission that could outlive this trusted app connection.
                args.SavesInProfile = false;
                args.State = args.PermissionKind == CoreWebView2PermissionKind.ClipboardRead
                    && DesktopPolicy.IsClipboardOrigin(args.Uri, core.Source, allowedPorts)
                    ? CoreWebView2PermissionState.Allow : CoreWebView2PermissionState.Deny;
            };
        }

        private async Task ResetOldClipboardDenials()
        {
            // Clear only this app's old persisted ClipboardRead=Deny entries so
            // the origin-scoped automatic handler above can decide again.
            // Never clear cookies, other permission kinds, or unrelated sites.
            var profile = browser.CoreWebView2.Profile;
            foreach (var setting in await profile.GetNonDefaultPermissionSettingsAsync())
            {
                if (setting.PermissionKind != CoreWebView2PermissionKind.ClipboardRead
                    || setting.PermissionState != CoreWebView2PermissionState.Deny) continue;
                bool appOrigin = allowedPorts.Any(port => DesktopPolicy.IsClipboardOrigin(
                    setting.PermissionOrigin, "http://127.0.0.1:" + port, allowedPorts));
                if (appOrigin) await profile.SetPermissionStateAsync(setting.PermissionKind,
                    setting.PermissionOrigin, CoreWebView2PermissionState.Default);
            }
        }

        private async Task<Dictionary<string, object>> Bootstrap(string operation)
        {
            return await Task.Run(async delegate
            {
                string python = Path.Combine(root, ".venv", "Scripts", "python.exe");
                if (!File.Exists(python)) throw new Exception("找不到仓库的 .venv\\Scripts\\python.exe，请先安装运行环境。");
                var info = new ProcessStartInfo(python)
                {
                    Arguments = DesktopPolicy.QuoteArgument(Path.Combine(root, "desktop", "bootstrap.py")) + " --root " + DesktopPolicy.QuoteArgument(root) + " " + operation,
                    WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true,
                    RedirectStandardOutput = true, RedirectStandardError = true,
                    StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
                };
                using (var process = Process.Start(info))
                {
                    var outputTask = process.StandardOutput.ReadToEndAsync();
                    var errorTask = process.StandardError.ReadToEndAsync();
                    var wait = Task.Run(delegate { return process.WaitForExit(260000); });
                    if (!await wait) { process.Kill(); throw new Exception("服务启动超时，请查看运行日志。"); }
                    string output = await outputTask;
                    await errorTask;
                    Dictionary<string, object> result;
                    try { result = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(output.Trim()); }
                    catch (Exception) { throw new Exception("启动器没有返回有效结果。请检查 .runtime/desktop 日志和 Python 环境。"); }
                    if (result == null || !result.ContainsKey("ok") || !Convert.ToBoolean(result["ok"]))
                        throw new Exception(result != null && result.ContainsKey("error") ? Convert.ToString(result["error"]) : "后台检查失败");
                    return result;
                }
            });
        }

        private async Task CheckHealth()
        {
            if (checkingHealth || starting || closing) return;
            checkingHealth = true;
            try
            {
                // Poll one lightweight endpoint, not a new Python process every 15s.
                await Task.Run(delegate
                {
                    var request = (HttpWebRequest)WebRequest.Create(origin + "/api/remote/runtime");
                    request.Proxy = null; request.Timeout = 3000; request.ReadWriteTimeout = 3000;
                    using (var response = (HttpWebResponse)request.GetResponse())
                    using (var reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8))
                    {
                        if (!response.ContentType.Contains("application/json")) throw new Exception("Unexpected service");
                        var runtime = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(reader.ReadToEnd());
                        if (runtime == null || !runtime.ContainsKey("system") || Convert.ToString(runtime["system"]) != "Windows"
                            || !runtime.ContainsKey("id") || Convert.ToString(runtime["id"]) != "") throw new Exception("Unexpected runtime");
                        if (runtime.ContainsKey("app_root") && !String.Equals(Path.GetFullPath(Convert.ToString(runtime["app_root"])), root, StringComparison.OrdinalIgnoreCase))
                            throw new Exception("Different repository");
                    }
                });
                if (!closing)
                {
                    connection.Text = "本机后台 · 已连接";
                    if (Text.StartsWith("[后台已断开]") && browser != null && browser.CoreWebView2 != null)
                        Text = browser.CoreWebView2.DocumentTitle.Replace(" - Void", " - EgoAgent");
                }
            }
            catch (Exception) { if (!closing) { connection.Text = "后台已断开 · 使用“检查 / 恢复连接”"; Text = "[后台已断开] EgoAgent"; } }
            finally { checkingHealth = false; }
        }

        private void LoadRemotePorts()
        {
            try
            {
                string path = Path.Combine(root, ".egoagent", "remote_workspaces.json");
                if (!File.Exists(path)) return;
                var profiles = new JavaScriptSerializer().Deserialize<List<Dictionary<string, object>>>(File.ReadAllText(path));
                foreach (var profile in profiles)
                {
                    int port;
                    if (profile.ContainsKey("port") && Int32.TryParse(Convert.ToString(profile["port"]), out port) && port >= 1024 && port <= 65535) allowedPorts.Add(port);
                }
            }
            catch (Exception) { }
        }

        private void PickFolder()
        {
            using (var dialog = new FolderBrowserDialog { Description = "选择本机项目文件夹。SSH / WSL 请使用 Chat 中的远程入口。", SelectedPath = saved.Workspace, ShowNewFolderButton = true })
                if (dialog.ShowDialog(this) == DialogResult.OK) NavigateFolder(dialog.SelectedPath);
        }

        private void NavigateFolder(string folder)
        {
            if (!Directory.Exists(folder)) { MessageBox.Show(this, "目录不存在：" + folder); return; }
            if (browser == null || browser.CoreWebView2 == null || origin == null) { MessageBox.Show(this, "请先等待服务连接完成。"); return; }
            browser.CoreWebView2.Navigate(DesktopPolicy.WorkspaceUrl(origin, folder));
        }

        private void RememberWorkspace()
        {
            if (browser == null || browser.CoreWebView2 == null || origin == null) return;
            Uri current;
            if (!Uri.TryCreate(browser.CoreWebView2.Source, UriKind.Absolute, out current) || current.Port != new Uri(origin).Port) return;
            string folder = DesktopPolicy.WorkspaceFromUrl(current.AbsoluteUri);
            if (folder == null) return;
            saved.Workspace = folder;
            saved.Recent.RemoveAll(path => path.Equals(folder, StringComparison.OrdinalIgnoreCase));
            saved.Recent.Insert(0, folder); saved.Recent = saved.Recent.Take(12).ToList();
            SaveState(); UpdateRecent();
        }

        private void UpdateRecent()
        {
            recent.DropDownItems.Clear();
            foreach (string item in saved.Recent)
            {
                string path = item;
                recent.DropDownItems.Add(path, null, delegate { NavigateFolder(path); });
            }
            recent.Enabled = recent.DropDownItems.Count > 0;
        }

        private void SaveState()
        {
            try
            {
                var bounds = WindowState == FormWindowState.Normal ? Bounds : RestoreBounds;
                saved.Width = bounds.Width; saved.Height = bounds.Height;
                saved.Maximized = WindowState == FormWindowState.Maximized;
                saved.Save(statePath);
            }
            catch (Exception) { /* A read-only profile must not take down the editor. */ }
        }

        private async Task StopServices()
        {
            if (MessageBox.Show(this, "将停止桌面版启动的后台，正在运行的 Agent、终端和远程连接可能被中断。\n\n请先保存文件。确定停止吗？", "停止后台服务", MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes) return;
            try { var result = await Bootstrap("--stop"); MessageBox.Show(this, Convert.ToString(result["message"]), "EgoAgent"); }
            catch (Exception error) { MessageBox.Show(this, error.Message, "无法停止"); }
        }

        private void OnClosing(object sender, FormClosingEventArgs args)
        {
            // Keep background runs alive; never kill a shared service on close.
            if (browser != null && browser.CoreWebView2 != null && MessageBox.Show(this,
                "关闭这个窗口？未保存的编辑内容请先保存。\n\n后台 Agent 和服务会继续运行，下次双击图标即可重新打开。", "关闭 EgoAgent 窗口", MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes)
            { args.Cancel = true; return; }
            closing = true; healthTimer.Stop(); SaveState();
        }

        private void ShowError(string message)
        {
            if (closing) return;
            status.Text = "EgoAgent 暂时无法打开\n\n" + message + "\n\n不会修改防火墙、结束未知进程或清除你的项目数据。";
            actions.Visible = true; loading.Visible = true; loading.BringToFront();
            connection.Text = "未连接";
        }

        private void Reload() { if (browser != null && browser.CoreWebView2 != null) browser.CoreWebView2.Reload(); }
        private void OpenLogs() { Directory.CreateDirectory(Path.Combine(root, ".runtime", "desktop")); Process.Start(new ProcessStartInfo("explorer.exe", DesktopPolicy.QuoteArgument(Path.Combine(root, ".runtime", "desktop"))) { UseShellExecute = true }); }
        private static void OpenExternal(string uri) { try { Process.Start(new ProcessStartInfo(uri) { UseShellExecute = true }); } catch (Exception) { } }
    }
}
