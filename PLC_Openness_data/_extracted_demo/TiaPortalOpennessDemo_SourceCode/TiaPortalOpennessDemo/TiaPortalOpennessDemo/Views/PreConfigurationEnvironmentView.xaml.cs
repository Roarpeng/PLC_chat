using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Input;

namespace TiaPortalOpennessDemo.Views
{
    /// <summary>
    /// Interaction logic for PreConfigurationEnvironmentView.xaml
    /// </summary>
    public partial class PreConfigurationEnvironmentView
    {
        public PreConfigurationEnvironmentView()
        {
            InitializeComponent();
        }

        private void ModuleExpansionsPath_OnKeyDown(object sender, KeyEventArgs e)
        {
            if (sender is TextBox textBox)
            {
                if (e.Key == Key.Enter)
                {
                    BindingExpression bindingExpression = textBox.GetBindingExpression(TextBox.TextProperty);
                    if (bindingExpression != null) bindingExpression.UpdateSource();
                }
            }
        }
    }
}
