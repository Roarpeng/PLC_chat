using System;

namespace TiaPortalOpennessCore.Contracts
{
    /// <summary>
    /// The ICloseWindow interface defines the contract for the closing mechanism of windows.
    /// </summary>
    public interface ICloseWindow
    {
        /// <summary>
        /// Action that must be carried out when closing a window.
        /// </summary>
        Action Close { get; set; }

        /// <summary>
        /// The return value of the window as a boolean.
        /// The default value is false.
        /// </summary>
        bool? DialogResult { get; set; }

        /// <summary>
        /// Return the value that indicates whether the window can be closed or not.
        /// The default value is true.
        /// </summary>
        /// <returns></returns>
        bool CanClose();
    }
}
