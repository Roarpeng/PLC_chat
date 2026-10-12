using System;
using System.Reflection;
using System.Windows.Forms;
using TiaPortalOpennessAdapter.Utils;
using TiaPortalOpennessDemo.Properties;

namespace TiaPortalOpennessDemo
{
    /// <summary>
    /// The main application object
    /// </summary>
    public static class Program
    {
        /// <summary>
        /// Defines the entry point of the application.
        /// </summary>
        [STAThread]
        public static void Main()
        {
            try
            {
                if (!Resolver.IsOpennessInstalled())
                {
                    throw new Exception(
                        $"The TIA Portal Openness minimum version required {Resolver.StrRequiredVersion}{Environment.NewLine} or a higher version is not installed.");
                }

                AppDomain.CurrentDomain.UnhandledException += CurrentDomain_UnhandledException;
                AppDomain.CurrentDomain.ReflectionOnlyAssemblyResolve += CurrentDomain_ReflectionOnlyAssemblyResolve;
                App.Main();
            }
            catch (Exception ex)
            {
                MessageBox.Show(string.Format(Resources.IsOpennessInstalled_Exception_Info_Message, ex.Message, Environment.NewLine, Environment.NewLine, Environment.NewLine, ex), Resources.IsOpennessInstalled_Exception_Info_Message_Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        /// <summary>
        /// Called to determine the expansion modules.
        /// </summary>
        /// <param name="sender">The caller</param>
        /// <param name="args">The requested assembly information as parameter</param>
        /// <returns>The requested assembly</returns>
        private static Assembly CurrentDomain_ReflectionOnlyAssemblyResolve(object sender, ResolveEventArgs args)
        {
            var assembly = Assembly.ReflectionOnlyLoad(args.Name);
            if (assembly != null)
            {
                return assembly;
            }
            else
            {
                return null; //throw new TypeLoadException("Could not load assembly - " + args.Name);
            }
        }

        /// <summary>
        /// Catches all unhandled exceptions
        /// </summary>
        /// <param name="sender">The source of the exception</param>
        /// <param name="e">The content of the exception</param>
        private static void CurrentDomain_UnhandledException(object sender, UnhandledExceptionEventArgs e)
        {
            if (e.ExceptionObject is Exception ex) System.Windows.MessageBox.Show(ex.Message);
        }
    }
}
