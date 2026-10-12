using System;
using System.IO;
using System.Linq;

namespace TiaPortalOpennessAdapterService.Utils
{
    /// <summary>
    /// Implementation of project path extension 
    /// </summary>
    public static class ProjectPathExtension
    {
        /// <summary>
        /// Get *.als Extension for local session 
        /// </summary>
        /// <param name="amcFileInfo"></param>
        /// <param name="fallbackToAmc"></param>
        /// <returns></returns>
        public static FileInfo ToLocalSessionFileInfo(this FileInfo amcFileInfo, bool fallbackToAmc = true)
        {
            if (amcFileInfo == null) throw new ArgumentNullException(nameof(amcFileInfo));
            if (!amcFileInfo.Extension.StartsWith(".amc", StringComparison.OrdinalIgnoreCase)) throw new NotSupportedException("The file type is not supported.");

            var localSessionFileInfo = amcFileInfo.Directory?.Parent?.EnumerateFiles("*.als*", SearchOption.TopDirectoryOnly).FirstOrDefault();
            return localSessionFileInfo ?? (fallbackToAmc ? amcFileInfo : null);
        }
    }
}
