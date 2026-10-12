using System;
using System.Globalization;
using System.Windows;
using System.Windows.Data;

namespace TiaPortalOpennessCore.Utils
{
    /// <summary>
    /// Boolean to visibility converter
    /// </summary>
    public class BoolToVisibilityConverter : IValueConverter
    {
        /// <summary>
        /// Converts a boolean value to visibility
        /// </summary>
        /// <param name="value">The value of the bonded property</param>
        /// <param name="targetType">The type of the target control</param>
        /// <param name="parameter">Parameter is not used</param>
        /// <param name="culture">Culture info is not used</param>
        /// <returns></returns>
        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
        {
            try
            {
                if (value == null)
                    throw new InvalidCastException(nameof(value) + " must not be null");

                var visibilityIndicator = (bool)value;
                return visibilityIndicator ? Visibility.Visible : Visibility.Collapsed;
            }
            catch (InvalidCastException)
            {
                return Visibility.Collapsed;
            }
        }

        /// <summary>
        /// Converts visibility back to boolean
        /// </summary>
        /// <param name="value">The visibility of the source control</param>
        /// <param name="targetType">The type of the bonded property</param>
        /// <param name="parameter">Parameter is not used</param>
        /// <param name="culture">Culture info is not used</param>
        /// <returns></returns>
        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
        {
            try
            {
                if (value == null)
                    throw new InvalidCastException(nameof(value) + " must not be null");

                var booleanIndicator = (Visibility)value;
                return (booleanIndicator == Visibility.Visible) ? (object)true : false;
            }
            catch (InvalidCastException)
            {
                return false;
            }
        }
    }
}
