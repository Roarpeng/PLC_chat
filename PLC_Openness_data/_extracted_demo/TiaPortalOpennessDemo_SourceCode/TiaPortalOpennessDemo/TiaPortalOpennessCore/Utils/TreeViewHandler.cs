using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using System.Windows.Controls;
using TiaPortalOpennessCore.Commands;

namespace TiaPortalOpennessCore.Utils
{
    /// <summary>
    /// ToDo Implementation needs to be revised
    /// Implementation of tree Handler
    /// </summary>
    public class TreeViewHandler
    {
        /// <summary>Gets the view.</summary>
        /// <value>The view.</value>
        public ObservableCollection<TreeView> View { get; }

        /// <summary>Gets or sets the selected item.</summary>
        /// <value>The selected item.</value>
        public TreeViewItem SelectedItem { get; set; }

        /// <summary>Gets or sets the selected item CHG command.</summary>
        /// <value>The selected item CHG command.</value>
        public RelayCommand<DependencyPropertyEventArgs> SelectedItemChgCmd { get; set; }

        /// <summary>Gets or sets the selected item CHG variable command.</summary>
        /// <value>The selected item CHG variable command.</value>
        public RelayCommand<DependencyPropertyEventArgs> SelectedItemChgVarCmd { get; set; }

        /// <summary>
        /// Initializes a new instance of the <see cref="TreeViewHandler"/> class.
        /// </summary>
        /// <param name="chgCmd">The CHG command.</param>
        public TreeViewHandler(RelayCommand<DependencyPropertyEventArgs> chgCmd)
        {
            SelectedItemChgCmd = chgCmd;
            SelectedItemChgVarCmd = chgCmd;
            SelectedItem = new TreeViewItem();
            View = new ObservableCollection<TreeView>();
        }

        /// <summary>Refreshes the specified view.</summary>
        /// <param name="view">The view.</param>
        public void Refresh(TreeView view)
        {
            if (View.Count != 0)
            {
                var treeState = SaveTreeState(View[0]);
                View.Clear();
                View.Add(view);
                RestoreTreeState(View[0], treeState);
            }
            else
            {
                View.Clear();
                View.Add(view);
            }
            SelectedItem = new TreeViewItem();
        }

        /// <summary>Saves the state of the tree.</summary>
        /// <param name="view">The view.</param>
        /// <returns></returns>
        private Dictionary<string, bool> SaveTreeState(ItemsControl view)
        {
            var nodeStates = new Dictionary<string, bool>();

            foreach (var item in view.Items)
            {
                var currentContainer = view.ItemContainerGenerator.ContainerFromItem(item) as TreeViewItem;
                if (currentContainer != null && currentContainer.Items.Count > 0)
                {
                    // Expand the current item. 
                    try
                    {
                        nodeStates.Add(currentContainer.Header.ToString(), currentContainer.IsExpanded);
                    }
                    catch
                    {
                        // ignored
                    }
                    SaveTreeState(currentContainer).ToList().ForEach(x => nodeStates[x.Key] = x.Value);
                }
            }

            return nodeStates;
        }

        /// <summary>Restores the state of the tree.</summary>
        /// <param name="view">The view.</param>
        /// <param name="treeState">State of the tree.</param>
        private void RestoreTreeState(ItemsControl view, Dictionary<string, bool> treeState)
        {
            foreach (TreeViewItem currentContainer in view.Items)
            {
                if (currentContainer != null && currentContainer.HasItems)
                {
                    if (treeState.ContainsKey(currentContainer.Header.ToString()))
                        currentContainer.IsExpanded = treeState[currentContainer.Header.ToString()];
                    RestoreTreeState(currentContainer, treeState);
                }
            }
        }

        /// <summary>
        /// Reset the background color of each tree item
        /// </summary>
        /// <param name="view"></param>
        public void ClearBackground(ItemsControl view)
        {
            foreach (TreeViewItem item in view.Items)
            {
                item.Background = null;

                var currentContainer = view.ItemContainerGenerator.ContainerFromItem(item) as TreeViewItem;
                if (currentContainer != null && currentContainer.Items.Count > 0)
                {
                    ClearBackground(currentContainer);
                }
            }
        }
    }
}
