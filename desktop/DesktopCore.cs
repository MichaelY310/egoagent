using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Web;
using System.Web.Script.Serialization;

namespace EgoAgentDesktop
{
    // No host-object / arbitrary JS-to-process bridge is exposed by this app.
    internal static class DesktopPolicy
    {
        public static bool IsInternal(string value, ISet<int> ports)
        {
            Uri uri;
            return Uri.TryCreate(value, UriKind.Absolute, out uri) && uri.Scheme == "http"
                && String.IsNullOrEmpty(uri.UserInfo)
                && (uri.Host.Equals("127.0.0.1", StringComparison.OrdinalIgnoreCase)
                    || uri.Host.Equals("localhost", StringComparison.OrdinalIgnoreCase))
                && ports.Contains(uri.Port);
        }

        public static bool IsExternal(string value)
        {
            Uri uri;
            return Uri.TryCreate(value, UriKind.Absolute, out uri) && String.IsNullOrEmpty(uri.UserInfo)
                && (uri.Scheme == "https" || uri.Scheme == "http" || uri.Scheme == "mailto");
        }

        public static bool IsClipboardOrigin(string value, string topLevel, ISet<int> ports)
        {
            Uri uri, top;
            if (!IsInternal(topLevel, ports) || !Uri.TryCreate(topLevel, UriKind.Absolute, out top)
                || !Uri.TryCreate(value, UriKind.Absolute, out uri) || uri.Scheme != "http"
                || !String.IsNullOrEmpty(uri.UserInfo) || uri.Port != top.Port) return false;
            // VS Code webviews are origin-isolated under <id>.localhost.
            // Only the active editor connection can ask, not other local ports.
            return uri.Host == "127.0.0.1" || uri.Host == "localhost"
                || System.Text.RegularExpressions.Regex.IsMatch(uri.Host, @"^[a-z0-9-]+\.localhost$");
        }

        public static string WorkspaceUrl(string origin, string folder)
        {
            string path = Path.GetFullPath(folder).Replace('\\', '/');
            if (!path.StartsWith("/")) path = "/" + path;
            return origin.TrimEnd('/') + "/?folder=" + Uri.EscapeDataString(path);
        }

        public static string WorkspaceFromUrl(string value)
        {
            Uri uri;
            if (!Uri.TryCreate(value, UriKind.Absolute, out uri)) return null;
            string path = HttpUtility.ParseQueryString(uri.Query)["folder"];
            if (String.IsNullOrWhiteSpace(path)) return null;
            if (path.Length > 3 && path[0] == '/' && path[2] == ':') path = path.Substring(1);
            try { return Directory.Exists(path) ? Path.GetFullPath(path) : null; }
            catch (Exception) { return null; }
        }

        public static string RootKey(string root)
        {
            using (var sha = SHA256.Create())
                return BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(Path.GetFullPath(root).ToLowerInvariant()))).Replace("-", "").Substring(0, 16);
        }

        public static string QuoteArgument(string value)
        {
            // Windows CommandLineToArgvW inverse, including trailing slashes.
            var output = new StringBuilder("\"");
            int slashes = 0;
            foreach (char character in value)
            {
                if (character == '\\') { slashes++; continue; }
                output.Append('\\', character == '"' ? slashes * 2 + 1 : slashes);
                output.Append(character);
                slashes = 0;
            }
            output.Append('\\', slashes * 2);
            return output.Append('"').ToString();
        }
    }

    internal sealed class DesktopState
    {
        public string Workspace { get; set; }
        public int Width { get; set; }
        public int Height { get; set; }
        public bool Maximized { get; set; }
        public List<string> Recent { get; set; }

        public static DesktopState Load(string path, string root)
        {
            try
            {
                var value = new JavaScriptSerializer().Deserialize<DesktopState>(File.ReadAllText(path));
                if (value != null)
                {
                    if (!Directory.Exists(value.Workspace)) value.Workspace = root;
                    value.Recent = (value.Recent ?? new List<string>()).Where(Directory.Exists).Take(12).ToList();
                    return value;
                }
            }
            catch (Exception) { }
            return new DesktopState { Workspace = root, Width = 1440, Height = 920, Recent = new List<string>() };
        }

        public void Save(string path)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            string temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            File.WriteAllText(temporary, new JavaScriptSerializer().Serialize(this), new UTF8Encoding(false));
            try
            {
                if (File.Exists(path)) File.Replace(temporary, path, null);
                else File.Move(temporary, path);
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }
    }
}
