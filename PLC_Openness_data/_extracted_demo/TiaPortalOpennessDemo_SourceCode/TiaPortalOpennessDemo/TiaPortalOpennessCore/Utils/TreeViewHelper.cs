using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;

namespace TiaPortalOpennessCore.Utils
{
    /// <summary>
    /// ToDo Implementation needs to be revised
    /// </summary>
    public sealed class TreeViewHelper
    {
        #region SelectedItem

        /// <summary>Gets the selected item.</summary>
        /// <param name="obj">The object.</param>
        /// <returns>Object</returns>
        public static object GetSelectedItem(DependencyObject obj)
        {
            return obj.GetValue(SelectedItemProperty);
        }

        /// <summary>Sets the selected item.</summary>
        /// <param name="obj">The object.</param>
        /// <param name="value">The value.</param>
        public static void SetSelectedItem(DependencyObject obj, object value)
        {
            obj.SetValue(SelectedItemProperty, value);
        }

        /// <summary>
        /// The selected item property
        /// </summary>
        public static readonly DependencyProperty SelectedItemProperty =
            DependencyProperty.RegisterAttached("SelectedItem",
                typeof(object),
                typeof(TreeViewHelper),
                new UIPropertyMetadata(null, SelectedItemChanged));

        /// <summary>Selected item changed.</summary>
        /// <param name="obj">The object.</param>
        /// <param name="e">The <see cref="DependencyPropertyChangedEventArgs"/> instance containing the event data.</param>
        private static void SelectedItemChanged(DependencyObject obj, DependencyPropertyChangedEventArgs e)
        {
            var view = obj as TreeView;

            if (view == null || e.NewValue == null)
                return;

            view.SelectedItemChanged += (sender, e2) => SetSelectedItem(view, e2.NewValue);

            var command = (ICommand)view.GetValue(SelectedItemChangedProperty);
            if (command != null)
            {
                if (command.CanExecute(null))
                    command.Execute(new DependencyPropertyEventArgs(e));
            }
        }

        #endregion

        #region Selected Item Changed

        /// <summary>Gets the selected item changed.</summary>
        /// <param name="obj">The object.</param>
        /// <returns>ICommand</returns>
        public static ICommand GetSelectedItemChanged(DependencyObject obj)
        {
            return (ICommand)obj.GetValue(SelectedItemProperty);
        }

        /// <summary>Sets the selected item changed.</summary>
        /// <param name="obj">The object.</param>
        /// <param name="value">The value.</param>
        public static void SetSelectedItemChanged(DependencyObject obj, ICommand value)
        {
            obj.SetValue(SelectedItemProperty, value);
        }

        /// <summary>
        /// The selected item changed property
        /// </summary>
        public static readonly DependencyProperty SelectedItemChangedProperty =
            DependencyProperty.RegisterAttached("SelectedItemChanged", typeof(ICommand), typeof(TreeViewHelper));

        #endregion

        #region Expanding Behavior

        /// <summary>
        /// The expanding behavior property
        /// </summary>
        public static readonly DependencyProperty ExpandingBehaviorProperty =
                DependencyProperty.RegisterAttached("ExpandingBehavior", typeof(ICommand), typeof(TreeViewHelper),
                    new UIPropertyMetadata(OnExpandingBehaviorChanged));


        /// <summary>Sets the expanding behavior.</summary>
        /// <param name="obj">The object.</param>
        /// <param name="value">The value.</param>
        public static void SetExpandingBehavior(DependencyObject obj, ICommand value)
        {
            obj.SetValue(ExpandingBehaviorProperty, value);
        }

        /// <summary>Gets the expanding behavior.</summary>
        /// <param name="obj">The object.</param>
        /// <returns>ICommand</returns>
        public static ICommand GetExpandingBehavior(DependencyObject obj)
        {
            return (ICommand)obj.GetValue(ExpandingBehaviorProperty);
        }

        /// <summary>
        /// Called when [expanding behavior changed].
        /// </summary>
        /// <param name="obj">The object.</param>
        /// <param name="e">The <see cref="DependencyPropertyChangedEventArgs"/> instance containing the event data.</param>
        private static void OnExpandingBehaviorChanged(DependencyObject obj, DependencyPropertyChangedEventArgs e)
        {
            var view = obj as TreeView;

            if (view == null || e.NewValue == null)
                return;

            view.SelectedItemChanged += (sender, e2) => SetSelectedItem(view, e2.NewValue);

            var command = (ICommand)view.GetValue(SelectedItemChangedProperty);
            if (command != null)
            {
                if (command.CanExecute(null))
                    command.Execute(new DependencyPropertyEventArgs(e));
            }
        }

        #endregion


        /// <summary>
        /// Prevents a default instance of the <see cref="TreeViewHelper"/> class from being created.
        /// </summary>
        private TreeViewHelper() { }
    }
    #region Event Args

    /// <summary>
    /// Dependency property event argument class provides the changed event arguments for the dependency property object
    /// </summary>
    /// <seealso cref="System.EventArgs" />
    public class DependencyPropertyEventArgs : EventArgs
    {
        /// <summary>Gets the dependency property changed event arguments.</summary>
        /// <value>The dependency property changed event arguments.</value>
        public DependencyPropertyChangedEventArgs DependencyPropertyChangedEventArgs { get; }

        /// <summary>
        /// Initializes a new instance of the <see cref="DependencyPropertyEventArgs"/> class.
        /// </summary>
        /// <param name="dependencyPropertyChangedEventArgs">The <see cref="DependencyPropertyChangedEventArgs"/> instance containing the event data.</param>
        public DependencyPropertyEventArgs(DependencyPropertyChangedEventArgs dependencyPropertyChangedEventArgs)
        {
            DependencyPropertyChangedEventArgs = dependencyPropertyChangedEventArgs;
        }
    }

    #endregion
}
