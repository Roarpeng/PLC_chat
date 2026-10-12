using System;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media.Animation;

namespace TiaPortalOpennessDemo.Views
{
    /// <summary>
    /// Interaction logic for ShellWindow.xaml
    /// </summary>
    public partial class ShellWindow
    {
        private bool _isTiaPortalPanelHide;
        private bool _isLibraryPanelHide;

        /// <summary>
        /// Default constructor
        /// </summary>
        public ShellWindow()
        {
            InitializeComponent();
            Deactivated += MainWindow_Deactivated;
            Closed += MainWindow_Closed;
            ShowTiaPortalSlidePanel.Click += ShowTiaPortalSlidePanelOnClick;
            HideTiaPortalSlidePanel.Click += HideTiaPortalSlidePanelOnClick;
            DockPanelMainView.MouseDown += DockPanelMainViewOnMouseDown;

            ShowLibrarySlidePanel.Click += ShowLibrarySlidePanelOnClick;
            HideLibrarySlidePanel.Click += HideLibrarySlidePanelOnClick;
            _isTiaPortalPanelHide = true;
            _isLibraryPanelHide = true;
        }

        private void MainWindow_Deactivated(object sender, EventArgs e)
        {
            //var window = (Window)sender;
            //window.Topmost = true;
        }

        /// <summary>
        /// 
        /// </summary>
        /// <param name="sender"></param>
        /// <param name="e"></param>
        private void DockPanelMainViewOnMouseDown(object sender, MouseButtonEventArgs e)
        {
            if (!_isTiaPortalPanelHide)
            {
                HideTiaPortalPanel();
                _isTiaPortalPanelHide = true;
            }

            if (!_isLibraryPanelHide)
            {
                HideLibraryPanel();
                _isLibraryPanelHide = true;
            }
        }

        /// <summary>
        /// 
        /// </summary>
        /// <param name="sender"></param>
        /// <param name="e"></param>
        private void HideTiaPortalSlidePanelOnClick(object sender, RoutedEventArgs e)
        {
            HideTiaPortalPanel();
            _isTiaPortalPanelHide = true;
        }

        /// <summary>
        /// 
        /// </summary>
        /// <param name="sender"></param>
        /// <param name="e"></param>
        private void ShowTiaPortalSlidePanelOnClick(object sender, RoutedEventArgs e)
        {
            if (_isTiaPortalPanelHide)
            {
                ShowTiaPortalPanel();
                _isTiaPortalPanelHide = false;
            }
            else
            {
                HideTiaPortalPanel();
                _isTiaPortalPanelHide = true;
            }
        }

        /// <summary>
        /// 
        /// </summary>
        /// <param name="sender"></param>
        /// <param name="e"></param>
        private void HideLibrarySlidePanelOnClick(object sender, RoutedEventArgs e)
        {
            HideLibraryPanel();
            _isLibraryPanelHide = true;
        }

        /// <summary>
        /// 
        /// </summary>
        /// <param name="sender"></param>
        /// <param name="e"></param>
        private void ShowLibrarySlidePanelOnClick(object sender, RoutedEventArgs e)
        {
            if (_isLibraryPanelHide)
            {
                ShowLibraryPanel();
                _isLibraryPanelHide = false;
            }
            else
            {
                HideLibraryPanel();
                _isLibraryPanelHide = true;
            }
        }

        /// <summary>
        /// 
        /// </summary>
        private void HideTiaPortalPanel()
        {
            Storyboard storyBoard = Resources["HideTiaPortalSlidePanel"] as Storyboard;
            if (storyBoard != null) storyBoard.Begin(TiaPortalSlidePanel);
        }

        /// <summary>
        /// 
        /// </summary>
        private void ShowTiaPortalPanel()
        {
            Storyboard storyBoard = Resources["ShowTiaPortalSlidePanel"] as Storyboard;
            if (storyBoard != null) storyBoard.Begin(TiaPortalSlidePanel);
        }

        /// <summary>
        /// 
        /// </summary>
        private void HideLibraryPanel()
        {
            Storyboard storyBoard = Resources["HideLibrarySlidePanel"] as Storyboard;
            if (storyBoard != null) storyBoard.Begin(LibrarySlidePanel);
        }

        /// <summary>
        /// 
        /// </summary>
        private void ShowLibraryPanel()
        {
            Storyboard storyBoard = Resources["ShowLibrarySlidePanel"] as Storyboard;
            if (storyBoard != null) storyBoard.Begin(LibrarySlidePanel);
        }

        /// <summary>
        /// Will be executed when the shell window is closed.
        /// </summary>
        /// <param name="sender">The shell window as trigger for the close event</param>
        /// <param name="e">event args</param>
        private void MainWindow_Closed(object sender, EventArgs e)
        {
            Application.Current.Shutdown();
        }
    }
}
