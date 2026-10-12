using Prism.Regions;
using System.Collections.Specialized;
using System.Windows;
using System.Windows.Controls;

namespace TiaPortalOpennessDemo.Adapter
{
    /// <summary>
    /// Custom region adapter for connecting a control item of type stack panel to a region.
    /// </summary>
    public class StackPanelRegionAdapter : RegionAdapterBase<StackPanel>
    {
        #region ctor

        /// <summary>
        /// Constructor
        /// </summary>
        /// <param name="regionBehaviorFactory">The region factory of the environment</param>
        public StackPanelRegionAdapter(IRegionBehaviorFactory regionBehaviorFactory)
            : base(regionBehaviorFactory)
        {
        }

        #endregion // ctor

        #region overrides

        /// <summary>
        /// Overridden Adapt method to provide the functionality to add or remove an element to or from a region.
        /// </summary>
        /// <param name="region">The region to be changed</param>
        /// <param name="regionTarget">The element to be added or removed</param>
        protected override void Adapt(IRegion region, StackPanel regionTarget)
        {
            region.Views.CollectionChanged += (s, e) =>
            {
                if (e.Action == NotifyCollectionChangedAction.Add)
                {
                    foreach (FrameworkElement element in e.NewItems)
                    {
                        regionTarget.Children.Add(element);
                    }
                }
                else if (e.Action == NotifyCollectionChangedAction.Remove)
                {
                    foreach (FrameworkElement element in e.OldItems)
                    {
                        regionTarget.Children.Remove(element);
                    }
                }
            };
        }

        /// <summary>
        /// Returns a new region.
        /// </summary>
        /// <returns></returns>
        protected override IRegion CreateRegion()
        {
            return new Region();
        }

        #endregion // overrides
    }
}
