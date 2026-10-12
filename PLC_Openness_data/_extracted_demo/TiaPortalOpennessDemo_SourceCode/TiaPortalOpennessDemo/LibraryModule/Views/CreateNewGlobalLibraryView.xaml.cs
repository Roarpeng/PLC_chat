using System.Windows;

namespace LibraryModule.Views
{
    /// <summary>
    /// Interaction logic for CreateNewGlobalLibraryView.xaml
    /// </summary>
    public partial class CreateNewGlobalLibraryView : Window
    {
        public CreateNewGlobalLibraryView()
        {
            InitializeComponent();
            Owner = System.Windows.Application.Current.MainWindow;
        }

        private void Path_TextChanged(object sender, System.Windows.Controls.TextChangedEventArgs e)
        {

        }
    }
}
