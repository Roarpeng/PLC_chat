using System.Windows;

namespace LibraryModule.Views
{
    /// <summary>
    /// Interaction logic for GroupEditorView.xaml
    /// </summary>
    public partial class GroupEditorView : Window
    {
        public GroupEditorView()
        {
            InitializeComponent();
            Owner = System.Windows.Application.Current.MainWindow;
        }
    }
}
