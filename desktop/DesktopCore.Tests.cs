using System;
using System.Collections.Generic;
using System.IO;
using EgoAgentDesktop;

internal static class DesktopTests
{
    private static int tests;
    private static void Check(bool condition, string name)
    {
        tests++;
        if (!condition) throw new Exception("FAILED: " + name);
    }

    public static int Main()
    {
        var ports = new HashSet<int> { 8880, 19100 };
        Check(DesktopPolicy.IsInternal("http://127.0.0.1:8880/?folder=x", ports), "local IDE");
        Check(DesktopPolicy.IsInternal("http://localhost:19100/", ports), "known remote connection");
        foreach (string url in new[] { "http://127.0.0.1:9999/", "http://127.0.0.1.evil.test:8880/", "http://evil.test:8880/", "http://user@localhost:8880/", "file:///C:/secret", "javascript:alert(1)", "cmd:/c", "https://localhost:8880/" })
            Check(!DesktopPolicy.IsInternal(url, ports), "reject " + url);
        Check(DesktopPolicy.IsExternal("https://example.org/"), "ordinary external link");
        Check(!DesktopPolicy.IsExternal("file:///C:/test.exe"), "do not launch executables");
        Check(!DesktopPolicy.IsExternal("javascript:alert(1)"), "do not execute script URLs");
        Check(!DesktopPolicy.IsExternal("http://name:secret@example.org/"), "do not forward credential URLs");
        string active = "http://127.0.0.1:19100/?folder=/home/project";
        Check(DesktopPolicy.IsClipboardOrigin(active, active, ports), "clipboard: active remote editor");
        Check(DesktopPolicy.IsClipboardOrigin("http://uuid-123.localhost:19100/index.html", active, ports), "clipboard: isolated webview");
        Check(DesktopPolicy.IsClipboardOrigin("http://localhost:19100/", active, ports), "clipboard: local alias");
        foreach (string url in new[] { "http://localhost:8880/", "http://localhost:9999/", "http://localhost.evil.test:19100/", "http://a.b.localhost:19100/", "http://user@localhost:19100/", "https://localhost:19100/", "file:///C:/secret", "https://example.com" })
            Check(!DesktopPolicy.IsClipboardOrigin(url, active, ports), "clipboard: reject " + url);
        Check(!DesktopPolicy.IsClipboardOrigin("http://localhost:19100/", "https://example.com", ports), "clipboard: reject foreign top-level page");
        string directory = Path.Combine(Path.GetTempPath(), "egoagent-desktop-tests-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        string project = Path.Combine(directory, "space & Unicode 中文 # +");
        Directory.CreateDirectory(project);
        try
        {
            string url = DesktopPolicy.WorkspaceUrl("http://127.0.0.1:8880", project);
            Check(DesktopPolicy.WorkspaceFromUrl(url) == project, "workspace path round trip");
            Check(DesktopPolicy.WorkspaceFromUrl("http://localhost:8880/") == null, "no workspace");
            var state = DesktopState.Load(Path.Combine(directory, "missing.json"), project);
            Check(state.Workspace == project && state.Recent.Count == 0, "first run defaults");
            string path = Path.Combine(directory, "window.json");
            state.Recent.Add(project); state.Save(path); state.Save(path);
            Check(DesktopState.Load(path, directory).Workspace == project, "atomic overwrite and restore");
            Check(DesktopState.Load(path, directory).Recent.Count == 1, "recent projects retained");
            File.WriteAllText(path, "invalid json");
            Check(DesktopState.Load(path, project).Workspace == project, "corrupt preferences recover");
            Check(DesktopPolicy.QuoteArgument("C:\\folder with space\\") == "\"C:\\folder with space\\\\\"", "trailing slash arguments");
            Check(DesktopPolicy.RootKey(project).Length == 16, "isolated browser profile key");
        }
        finally { Directory.Delete(directory, true); }
        Console.WriteLine(tests + " desktop policy/state tests passed");
        return 0;
    }
}
