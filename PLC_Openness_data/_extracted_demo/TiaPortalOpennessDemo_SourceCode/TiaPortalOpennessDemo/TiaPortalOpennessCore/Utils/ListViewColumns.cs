using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Controls;

namespace TiaPortalOpennessCore.Utils
{
    /// <summary>
    /// List view extension
    /// </summary>
    public class ListViewColumns : DependencyObject
    {
        /// <summary>
        /// Dependency property indicates, whether stretching the columns
        /// should be stretched over the available space or not
        /// </summary>
        public static readonly DependencyProperty StretchProperty =
            DependencyProperty.RegisterAttached("Stretch",
            typeof(bool),
            typeof(ListViewColumns),
            new PropertyMetadata(true, null, OnCoerceStretch));

        /// <summary>
        /// Getter of the dependency property
        /// </summary>
        /// <param name="dependencyObject">The dependency property</param>
        /// <returns>The value of the dependency property</returns>
        public static bool GetStretch(DependencyObject dependencyObject)
        {
            return (bool)dependencyObject.GetValue(StretchProperty);
        }

        /// <summary>
        /// Setter of the dependency property
        /// </summary>
        /// <param name="dependencyObject">The dependency property</param>
        /// <param name="value">The value to be set</param>
        public static void SetStretch(DependencyObject dependencyObject, bool value)
        {
            dependencyObject.SetValue(StretchProperty, value);
        }

        /// <summary>
        /// Coerce the stretch of the columns
        /// </summary>
        /// <param name="dependencyObject">The bonded source control</param>
        /// <param name="value">Flag that indicates, whether to be stretched or not</param>
        /// <returns>The Flag</returns>
        private static object OnCoerceStretch(DependencyObject dependencyObject, object value)
        {
            if (!(dependencyObject is ListView listView))
            {
                throw new ArgumentException("This property may only be used on list views");
            }

            listView.Loaded += ListView_Loaded;
            listView.SizeChanged += ListView_SizeChanged;

            return value;
        }

        /// <summary>
        /// Event handler is executed if the control size is changed
        /// </summary>
        /// <param name="sender">The source control</param>
        /// <param name="e">Event args</param>
        private static void ListView_SizeChanged(object sender, SizeChangedEventArgs e)
        {
            if (sender is ListView listView && listView.IsLoaded)
            {
                SetColumnWidth(listView);
            }
        }

        /// <summary>
        /// Event handler is executed if the control is loaded
        /// </summary>
        /// <param name="sender">The source control</param>
        /// <param name="e">Event args</param>
        private static void ListView_Loaded(object sender, RoutedEventArgs e)
        {
            var listView = sender as ListView;
            SetColumnWidth(listView);
        }

        /// <summary>
        /// Set the optimal column width for the available space
        /// </summary>
        /// <param name="listView">The source control</param>
        private static void SetColumnWidth(ListView listView)
        {
            List<GridViewColumn> columns = listView.Tag as List<GridViewColumn>;
            double specifiedWidth = 0;
            GridView gridView = listView.View as GridView;

            if (gridView != null)
            {
                if (columns == null)
                {
                    columns = new List<GridViewColumn>();
                    foreach (var column in gridView.Columns)
                    {
                        if (!(column.Width >= 0))
                        {
                            columns.Add(column);
                        }
                        else
                        {
                            specifiedWidth += column.ActualWidth;
                        }
                    }
                }
                else
                {
                    foreach (var column in gridView.Columns)
                    {
                        if (!columns.Contains(column))
                        {
                            specifiedWidth += column.ActualWidth;
                        }
                    }
                }

                foreach (var column in columns)
                {
                    double newWidth = (listView.ActualWidth - specifiedWidth) / columns.Count;
                    if (newWidth >= 10)
                    {
                        column.Width = newWidth - 10;
                    }
                }

                listView.Tag = columns;
            }
        }
    }
}
