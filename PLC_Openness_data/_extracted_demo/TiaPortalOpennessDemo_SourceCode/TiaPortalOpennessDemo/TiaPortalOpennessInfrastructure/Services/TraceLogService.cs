using System;
using System.Collections.ObjectModel;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using TiaPortalOpennessInfrastructure.Contracts;

namespace TiaPortalOpennessInfrastructure.Services
{
    /// <summary>
    /// Implementation of the trace log service for recording the process flow and user interaction.
    /// </summary>
    public class TraceLogService : TextWriter, ITraceLogService
    {
        #region fields

        private ObservableCollection<string> _list;
        private StringBuilder _content = new StringBuilder();

        #endregion // fields

        #region ctor
        #endregion // ctor

        #region properties

        /// <summary>
        /// List for log information
        /// </summary>
        public ObservableCollection<string> List
        {
            get => _list;
            set => _list = value;
        }

        /// <summary>
        /// Defines the encoding type
        /// </summary>
        public override Encoding Encoding => Encoding.UTF8;

        #endregion // properties

        #region methods

        /// <summary>
        /// Writes a log message to trace output
        /// </summary>
        /// <param name="value"></param>
        public override void Write(string value)
        {
            base.Write(value);

            if (List == null)
            {
                List = new ObservableCollection<string>();
            }
            var lines = value.Split('\n');
            bool firstLine = true;

            foreach (var line in lines)
            {
                string input = ReplaceSpecialCharacters(line);
                if (!string.IsNullOrEmpty(input) && !string.IsNullOrWhiteSpace(input))
                {
                    string timeStamp = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff");
                    if (firstLine)
                    {
                        _content.Append(timeStamp + "\t" + input);
                        firstLine = false;
                    }
                    else
                    {
                        _content.Append("\t\t\t" + input);
                    }

                    List.Insert(0, _content.ToString());
                    _content = new StringBuilder();
                }
            }
        }

        /// <summary>
        /// Replace special characters with space
        /// </summary>
        /// <param name="value"></param>
        /// <returns></returns>
        private string ReplaceSpecialCharacters(string value)
        {
            try
            {
                string result = Regex.Replace(value, @"\n|\r|\t", " ");

                return result;
            }
            catch
            {
                return string.Empty;
            }
        }

        #endregion // methods
    }
}
