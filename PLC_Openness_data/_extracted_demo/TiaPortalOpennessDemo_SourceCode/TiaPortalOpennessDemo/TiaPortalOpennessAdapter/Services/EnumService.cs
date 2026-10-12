using System;
using System.Runtime.CompilerServices;

namespace TiaPortalOpennessAdapter.Services
{
    /// <summary>
    /// EnumService is a helper to retrieve a enum object from string.
    /// e.g. your enum named 'BackgroundColor' looks like this
    /// Red = 1,
    /// Green = 2,
    /// Yellow = 3
    /// In the UI will be Red, Green and Yellow displayed as string list to select a
    /// color. But you need the enum object to set the selected background color.
    /// The EnumService gets the enum object from string you has been selected. e.g. call
    /// you the method GetEnumValue with the parameter 'Green' to get the Background.Green object.
    /// </summary>
    public static class EnumService
    {
        /// <summary>
        /// Get the enum value to a string
        /// </summary>
        /// <typeparam name="T">Enum Type</typeparam>
        /// <param name="value">String that represent the enum entry</param>
        /// <param name="caller">Who was I called by? This is for trace log!</param>
        /// <returns></returns>
        public static T GetEnumValue<T>(string value, [CallerMemberName] string caller = "") where T : struct, IConvertible
        {
            //MethodBase methodBase = MethodBase.GetCurrentMethod();
            //if (methodBase.ReflectedType != null)
            //    _traceWriter.Write(methodBase.ReflectedType.Name + "." + methodBase.Name + " called from " + caller);

            if (!typeof(T).IsEnum)
            {
                //_traceWriter.Write(@"T must be an Enumeration type!");
                throw new Exception(@"T must be an Enumeration type!");
            }

            T enumValue = ((T[])Enum.GetValues(typeof(T)))[0];

            if (!string.IsNullOrEmpty(value))
            {
                foreach (var itemValue in ((T[])Enum.GetValues(typeof(T))))
                {
                    if (itemValue.ToString().ToUpper().Equals(value.ToUpper()))
                    {
                        enumValue = itemValue;
                        break;
                    }
                }
            }

            return enumValue;
        }

    }
}
