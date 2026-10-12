using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;

namespace TiaPortalOpennessDemo.Controls
{
    /// <summary>
    /// Implementation of dock panel splitter  
    /// </summary>
    public class DockPanelSplitter : Control
    {
        #region fields

        private FrameworkElement _element;
        private double           _width;
        private double           _height;
        private double           _previousParentWidth;
        private double           _previousParentHeight;
        private Point            _startDragPoint;

        #endregion // fields

        #region ctor

        /// <summary>
        /// static default constructor
        /// </summary>
        static DockPanelSplitter()
        {
            DefaultStyleKeyProperty.OverrideMetadata(typeof(DockPanelSplitter), new FrameworkPropertyMetadata(typeof(DockPanelSplitter)));
            BackgroundProperty.OverrideMetadata(typeof(DockPanelSplitter), new FrameworkPropertyMetadata(Brushes.Transparent));
            DockPanel.DockProperty.OverrideMetadata(typeof(DockPanelSplitter), new FrameworkPropertyMetadata(Dock.Left, DockChanged));
        }

        /// <summary>
        /// instance constructor
        /// </summary>
        public DockPanelSplitter()
        {
            Loaded   += DockPanelSplitterLoaded;
            Unloaded += DockPanelSplitterUnloaded;
        }

        #endregion // ctor

        #region properties

        /// <summary>
        /// ToDo edit comment
        /// </summary>
        public bool ProportionalResize
        {
            get => (bool)GetValue(ProportionalResizeProperty);
            set => SetValue(ProportionalResizeProperty, value);
        }

        /// <summary>
        /// ToDo edit comment
        /// </summary>
        public double Thickness
        {
            get => (double)GetValue(ThicknessProperty);
            set => SetValue(ThicknessProperty, value);
        }

        /// <summary>
        /// ToDo edit comment
        /// </summary>
        public bool IsHorizontal
        {
            get
            {
                var dock = DockPanel.GetDock(this);
                return dock == Dock.Top || dock == Dock.Bottom;
            }
        }

        #endregion // properties

        #region dependency properties

        /// <summary>
        /// dependency property ProportionalResize
        /// </summary>
        public static readonly DependencyProperty ProportionalResizeProperty = DependencyProperty.Register("ProportionalResize", typeof(bool), typeof(DockPanelSplitter), new UIPropertyMetadata(true));

        /// <summary>
        /// dependency property Thickness
        /// </summary>
        public static readonly DependencyProperty ThicknessProperty = DependencyProperty.Register("Thickness", typeof(double), typeof(DockPanelSplitter), new UIPropertyMetadata(4.0, ThicknessChanged));

        #endregion // dependency properties

        #region methods

        /// <summary>
        /// When loaded, add event handler ParentSizeChanged and
        /// init width and height
        /// </summary>
        /// <param name="sender"></param>
        /// <param name="e"></param>
        private void DockPanelSplitterLoaded(object sender, RoutedEventArgs e)
        {
            Panel dp = Parent as Panel;
            if (dp == null) return;

            dp.SizeChanged += ParentSizeChanged;

            _previousParentWidth  = dp.ActualWidth;
            _previousParentHeight = dp.ActualHeight;

            UpdateTargetElement();
        }

        /// <summary>
        /// When unloaded, remove event handler ParentSizeChanged
        /// </summary>
        /// <param name="sender"></param>
        /// <param name="e"></param>
        private void DockPanelSplitterUnloaded(object sender, RoutedEventArgs e)
        {
            Panel dp = Parent as Panel;
            if (dp == null) return;

            dp.SizeChanged -= ParentSizeChanged;
        }

        /// <summary>
        /// Update height and width when dock changed
        /// </summary>
        /// <param name="d"></param>
        /// <param name="e"></param>
        private static void DockChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
        {
            ((DockPanelSplitter)d).UpdateHeightOrWidth();
        }

        /// <summary>
        /// Update height and width when thickness changed
        /// </summary>
        /// <param name="d"></param>
        /// <param name="e"></param>
        private static void ThicknessChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
        {
            ((DockPanelSplitter)d).UpdateHeightOrWidth();
        }

        /// <summary>
        /// Update height and width
        /// </summary>
        private void UpdateHeightOrWidth()
        {
            if (IsHorizontal)
            {
                Height = Thickness;
                Width  = double.NaN;
            }
            else
            {
                Width  = Thickness;
                Height = double.NaN;
            }
        }

        /// <summary>
        /// Update the target element
        /// </summary>
        private void UpdateTargetElement()
        {
            Panel dp = Parent as Panel;
            if (dp == null) return;

            int i = dp.Children.IndexOf(this);

            if (i > 0 && dp.Children.Count > 0)
            {
                _element = dp.Children[i - 1] as FrameworkElement;
            }
        }

        /// <summary>
        /// Set the target width
        /// </summary>
        /// <param name="newWidth"></param>
        private void SetTargetWidth(double newWidth)
        {
            if (newWidth < _element.MinWidth)
                newWidth = _element.MinWidth;
            if (newWidth > _element.MaxWidth)
                newWidth = _element.MaxWidth;

            Panel dp = Parent as Panel;
            Dock dock = DockPanel.GetDock(this);
            if (dp != null)
            {
                MatrixTransform t = _element.TransformToAncestor(dp) as MatrixTransform;
                if (t != null && dock == Dock.Left && newWidth > dp.ActualWidth - t.Matrix.OffsetX - Thickness)
                    newWidth = dp.ActualWidth - t.Matrix.OffsetX - Thickness;
            }

            _element.Width = newWidth;
        }

        /// <summary>
        /// Set the target height
        /// </summary>
        /// <param name="newHeight"></param>
        private void SetTargetHeight(double newHeight)
        {
            if (newHeight < _element.MinHeight)
                newHeight = _element.MinHeight;
            if (newHeight > _element.MaxHeight)
                newHeight = _element.MaxHeight;

            Panel dp = Parent as Panel;
            Dock dock = DockPanel.GetDock(this);
            if (dp != null)
            {
                MatrixTransform t = _element.TransformToAncestor(dp) as MatrixTransform;
                if (t != null && dock == Dock.Top && newHeight > dp.ActualHeight - t.Matrix.OffsetY - Thickness)
                    newHeight = dp.ActualHeight - t.Matrix.OffsetY - Thickness;
            }

            _element.Height = newHeight;
        }

        /// <summary>
        /// Set target height and width when parent size changed
        /// </summary>
        /// <param name="sender"></param>
        /// <param name="e"></param>
        private void ParentSizeChanged(object sender, SizeChangedEventArgs e)
        {
            if (!ProportionalResize) return;

            DockPanel dp = Parent as DockPanel;
            if (dp == null) return;

            double sx = dp.ActualWidth / _previousParentWidth;
            double sy = dp.ActualHeight / _previousParentHeight;

            if (!double.IsInfinity(sx))
                SetTargetWidth(_element.Width * sx);
            if (!double.IsInfinity(sy))
                SetTargetHeight(_element.Height * sy);

            _previousParentWidth  = dp.ActualWidth;
            _previousParentHeight = dp.ActualHeight;
        }

        /// <summary>
        /// Adjust target width
        /// </summary>
        /// <param name="dx"></param>
        /// <param name="dock"></param>
        /// <returns></returns>
        double AdjustWidth(double dx, Dock dock)
        {
            if (dock == Dock.Right)
                dx = -dx;

            _width += dx;
            SetTargetWidth(_width);

            return dx;
        }

        /// <summary>
        /// Adjust target height 
        /// </summary>
        /// <param name="dy"></param>
        /// <param name="dock"></param>
        /// <returns></returns>
        double AdjustHeight(double dy, Dock dock)
        {
            if (dock == Dock.Bottom)
                dy = -dy;

            _height += dy;
            SetTargetHeight(_height);

            return dy;
        }

        #endregion // methods

        #region overriedes

        /// <summary>
        /// On mouse enter processing
        /// </summary>
        /// <param name="e"></param>
        protected override void OnMouseEnter(MouseEventArgs e)
        {
            base.OnMouseEnter(e);
            if (!IsEnabled) return;

            Cursor = IsHorizontal ? Cursors.SizeNS : Cursors.SizeWE;
        }

        /// <summary>
        /// On mouse down processing
        /// </summary>
        /// <param name="e"></param>
        protected override void OnMouseDown(MouseButtonEventArgs e)
        {
            if (!IsEnabled) return;

            if (!IsMouseCaptured)
            {
                _startDragPoint = e.GetPosition(Parent as IInputElement);
                UpdateTargetElement();
                if (_element != null)
                {
                    _width = _element.ActualWidth;
                    _height = _element.ActualHeight;
                    CaptureMouse();
                }
            }

            base.OnMouseDown(e);
        }

        /// <summary>
        /// On mouse move processing
        /// </summary>
        /// <param name="e"></param>
        protected override void OnMouseMove(MouseEventArgs e)
        {
            if (IsMouseCaptured)
            {
                Point ptCurrent = e.GetPosition(Parent as IInputElement);
                Point delta = new Point(ptCurrent.X - _startDragPoint.X, ptCurrent.Y - _startDragPoint.Y);
                Dock dock = DockPanel.GetDock(this);

                if (IsHorizontal)
                    delta.Y = AdjustHeight(delta.Y, dock);
                else
                    delta.X = AdjustWidth(delta.X, dock);

                bool isBottomOrRight = (dock == Dock.Right || dock == Dock.Bottom);

                if (isBottomOrRight)
                    _startDragPoint = e.GetPosition(Parent as IInputElement);
                else
                    _startDragPoint = new Point(_startDragPoint.X + delta.X, _startDragPoint.Y + delta.Y);
            }

            base.OnMouseMove(e);
        }

        /// <summary>
        /// On mouse up processing
        /// </summary>
        /// <param name="e"></param>
        protected override void OnMouseUp(MouseButtonEventArgs e)
        {
            if (IsMouseCaptured)
            {
                ReleaseMouseCapture();
            }
            base.OnMouseUp(e);
        }

        #endregion // overrides
    }
}
