using System;
using System.Globalization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace TiaPortalOpennessDemoStyling.Utils
{
    /// <summary>
    /// Class used to have an image that is able to be gray when the control is not enabled.
    /// Based on the version by Thomas LEBRUN (http://blogs.developpeur.org/tom)
    /// </summary>
    /// <seealso cref="System.Windows.Controls.Image" />
    public class AutoGrayableImage : Image
    {
        /// <summary>
        /// Default constructor to initialize a new instance
        /// </summary>
        static AutoGrayableImage()
        {
            IsEnabledProperty.OverrideMetadata(typeof(AutoGrayableImage),
                new FrameworkPropertyMetadata(true, OnAutoGreyScaleImageIsEnabledPropertyChanged));
            SourceProperty.OverrideMetadata(typeof(AutoGrayableImage),
                new FrameworkPropertyMetadata(null, OnAutoGreyScaleImageSourcePropertyChanged));
        }

        /// <summary>Gets the image with source.</summary>
        /// <param name="source">The source image</param>
        /// <returns>Auto grayable image</returns>
        protected static AutoGrayableImage GetImageWithSource(DependencyObject source)
        {
            var image = source as AutoGrayableImage;

            return image?.Source == null ? null : image;
        }

        /// <summary>Called when [auto grey scale image source property changed].</summary>
        /// <param name="source">The source.</param>
        /// <param name="args">The <see cref="System.Windows.DependencyPropertyChangedEventArgs" /> instance containing the event data.</param>
        protected static void OnAutoGreyScaleImageSourcePropertyChanged(DependencyObject source,
            DependencyPropertyChangedEventArgs args)
        {
            var image = GetImageWithSource(source);
            if (image != null)
                ApplyGreyScaleImage(image, image.IsEnabled);
        }

        /// <summary>
        /// Called when [auto grey scale image is enabled property changed].
        /// </summary>
        /// <param name="source">The source.</param>
        /// <param name="args">The <see cref="System.Windows.DependencyPropertyChangedEventArgs" /> instance containing the event data.</param>
        protected static void OnAutoGreyScaleImageIsEnabledPropertyChanged(DependencyObject source,
            DependencyPropertyChangedEventArgs args)
        {
            var image = GetImageWithSource(source);
            if (image != null)
            {
                var isEnabled = Convert.ToBoolean(args.NewValue, CultureInfo.InvariantCulture);
                ApplyGreyScaleImage(image, isEnabled);
            }
        }

        /// <summary>Applies the grey scale image.</summary>
        /// <param name="autoGrayScaleImage">The automatic grey scale image.</param>
        /// <param name="isEnabled">if set to <c>true</c> [is enabled].</param>
        protected static void ApplyGreyScaleImage(Image autoGrayScaleImage, Boolean isEnabled)
        {
            try
            {
                if (!isEnabled)
                {
                    BitmapSource bitmapImage;

                    if (autoGrayScaleImage.Source is FormatConvertedBitmap)
                    {
                        // Already gray !
                        return;
                    }

                    if (autoGrayScaleImage.Source is BitmapSource)
                    {
                        bitmapImage = (BitmapSource)autoGrayScaleImage.Source;
                    }
                    else // trying string 
                    {
                        bitmapImage = new BitmapImage(new Uri(autoGrayScaleImage.Source.ToString()));
                    }

                    var conv = new FormatConvertedBitmap(bitmapImage, PixelFormats.Gray32Float, null, 0);
                    autoGrayScaleImage.Source = conv;

                    // Create Opacity Mask for grayscale image as FormatConvertedBitmap does not keep transparency info
                    autoGrayScaleImage.OpacityMask =
                        new ImageBrush(((FormatConvertedBitmap)autoGrayScaleImage.Source)
                            .Source); //equivalent to new ImageBrush(bitmapImage)
                }
                else
                {
                    if (autoGrayScaleImage.Source is FormatConvertedBitmap)
                    {
                        autoGrayScaleImage.Source = ((FormatConvertedBitmap)autoGrayScaleImage.Source).Source;
                    }
                    else if (autoGrayScaleImage.Source is BitmapSource)
                    {
                        // Should be full color already.
                        return;
                    }

                    // Reset the Opacity Mask
                    autoGrayScaleImage.OpacityMask = null;
                }
            }
            catch (ArgumentException)
            {
                // nothing'
            }
        }
    }
}
