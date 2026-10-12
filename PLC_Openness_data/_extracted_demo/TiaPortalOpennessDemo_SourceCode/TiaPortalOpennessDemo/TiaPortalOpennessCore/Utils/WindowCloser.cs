using System.Windows;
using TiaPortalOpennessCore.Contracts;

namespace TiaPortalOpennessCore.Utils
{
    /// <summary>
    /// Implementation of closing mechanism for windows.
    /// </summary>
    public class WindowCloser
    {
        /// <summary>
        /// Dependency Property for detecting whether a window can or may be closed.
        /// </summary>
        public static readonly DependencyProperty EnableWindowClosingProperty =
            DependencyProperty.RegisterAttached("EnableWindowClosing",
                typeof(bool),
                typeof(WindowCloser),
                new PropertyMetadata(false, OnEnableWindowClosingChanged));

        /// <summary>
        /// Get the value of the dependency property.
        /// </summary>
        /// <param name="obj">The object, that depends on the property.</param>
        /// <returns></returns>
        public static bool GetEnableWindowClosing(DependencyObject obj)
        {
            return (bool)obj.GetValue(EnableWindowClosingProperty);
        }

        /// <summary>
        /// Set the value of the dependency property.
        /// </summary>
        /// <param name="obj">The object whose dependency property is to be set.</param>
        /// <param name="value">The value to be set.</param>
        public static void SetEnableWindowClosing(DependencyObject obj, bool value)
        {
            obj.SetValue(EnableWindowClosingProperty, value);
        }

        /// <summary>
        /// The callback method of the dependency property that is called when the value of the property ist changed.
        /// </summary>
        /// <param name="dependencyObject">The object whose dependency property is to be changed.</param>
        /// <param name="dependencyObjectArgs">The given change event args.</param>
        private static void OnEnableWindowClosingChanged(DependencyObject dependencyObject, DependencyPropertyChangedEventArgs dependencyObjectArgs)
        {
            if (dependencyObject is Window window)
            {
                window.Loaded += (loadedObject, loadedObjectArgs) =>
                {
                    if (window.DataContext is ICloseWindow viewModel)
                    {
                        viewModel.Close += () =>
                        {
                            window.Close();
                        };

                        window.Closing += (closingObject, closingObjectArgs) =>
                        {
                            closingObjectArgs.Cancel = !viewModel.CanClose();
                        };
                    }
                };
            }
        }

        /// <summary>
        /// The dependency property to define the dialog result.
        /// </summary>
        public static readonly DependencyProperty DialogResultProperty =
            DependencyProperty.RegisterAttached("DialogResult",
                typeof(bool?),
                typeof(WindowCloser),
                new PropertyMetadata(OnDialogResultChanged));

        /// <summary>
        /// The callback method of the dependency property that is called when the value of the property ist changed.
        /// </summary>
        /// <param name="dependencyObject">The object whose dependency property is to be changed.</param>
        /// <param name="dependencyObjectArgs">The given change event args.</param>
        private static void OnDialogResultChanged(DependencyObject dependencyObject, DependencyPropertyChangedEventArgs dependencyObjectArgs)
        {
            var window = dependencyObject as Window;
            if (window != null && window.IsVisible)
            {
                window.DialogResult = dependencyObjectArgs.NewValue as bool?;
            }
        }

        /// <summary>
        /// Get the value of the dependency property.
        /// </summary>
        /// <param name="targetWindow">The receiver of the dependency property value.</param>
        /// <returns>The dependency property value.</returns>
        public static object GetDialogResult(Window targetWindow)
        {
            bool? result = null;

            if (targetWindow != null)
            {
                result = targetWindow.GetValue(DialogResultProperty) as bool?;
            }

            return result;
        }

        /// <summary>
        /// Set the value of the dependency property.
        /// </summary>
        /// <param name="targetWindow">The sender of the dependency property value.</param>
        /// <param name="value">The dependency property value.</param>
        public static void SetDialogResult(Window targetWindow, bool? value)
        {
            if (targetWindow != null)
            {
                targetWindow.SetValue(DialogResultProperty, value);
            }
        }
    }
}