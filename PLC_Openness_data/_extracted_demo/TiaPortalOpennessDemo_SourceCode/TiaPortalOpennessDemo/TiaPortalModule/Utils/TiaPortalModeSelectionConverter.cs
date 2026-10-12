using System;
using System.Globalization;
using System.Windows;
using System.Windows.Data;

namespace TiaPortalModule.Utils
{
    /// <summary>
    /// Value converter to decouple the application user interface from the siemens api.
    /// </summary>
    public class TiaPortalModeSelectionConverter : IValueConverter
    {
        /// <summary>
        /// Retrieve true or false if the value equals parameter or not  
        /// </summary>
        /// <param name="value">Reference value</param>
        /// <param name="targetType">target type - boolean</param>
        /// <param name="parameter">parameter value - selected option as string</param>
        /// <param name="culture">culture info object</param>
        /// <returns></returns>
        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
        {
            if (value == null)
                throw new ArgumentNullException(nameof(value) + " cannnot be null");

            var parameterString = parameter as string;
            if (parameterString == null)
            {
                return DependencyProperty.UnsetValue;
            }

            if (Enum.IsDefined(value.GetType(), value) == false)
            {
                return DependencyProperty.UnsetValue;
            }

            object parameterValue = Enum.Parse(value.GetType(), parameterString);

            return parameterValue.Equals(value);
        }

        /// <summary>
        /// Retrieve the siemens enum value 
        /// </summary>
        /// <param name="value">Reference value - true or false</param>
        /// <param name="targetType">siemens enum type - start mode</param>
        /// <param name="parameter">parameter value - selected option as string</param>
        /// <param name="culture">culture info object</param>
        /// <returns></returns>
        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
        {
            if (value == null)
                throw new ArgumentNullException(nameof(value) + " cannot be null");

            var parameterString = parameter as string;
            var valueAsBool = (bool)value;

            if (parameterString != null && !valueAsBool)
            {
                try
                {
                    return Enum.Parse(targetType, "1");
                }
                catch (Exception)
                {
                    return DependencyProperty.UnsetValue;
                }
            }

            if (parameterString == null)
            {
                try
                {
                    return Enum.Parse(targetType, "0");
                }
                catch (Exception)
                {
                    return DependencyProperty.UnsetValue;
                }
            }

            return Enum.Parse(targetType, parameterString);
        }
    }
}
