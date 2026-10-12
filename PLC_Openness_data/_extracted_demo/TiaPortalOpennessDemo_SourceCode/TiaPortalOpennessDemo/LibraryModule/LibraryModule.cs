using LibraryModule.Views;
using Prism.Ioc;
using Prism.Modularity;
using Prism.Regions;
using TiaPortalOpennessInfrastructure.Constants;

namespace LibraryModule
{
    /// <summary>
    /// Library module
    /// </summary>
    public class LibraryModule : IModule
    {
        private readonly IRegionManager _regionManager;

        /// <summary>
        /// Default constructor with injection (late binding)
        /// </summary>
        /// <param name="regionManager">Injected region manager</param>
        public LibraryModule(IRegionManager regionManager)
        {
            _regionManager = regionManager;
        }

        /// <summary>
        /// Registrations of a view for a target region, it composites the application
        /// </summary>
        /// <param name="containerRegistry">Container registry for registration certain types</param>
        public void RegisterTypes(IContainerRegistry containerRegistry)
        {
            containerRegistry.Register(typeof(GroupEditorView));
            containerRegistry.Register(typeof(CreateNewGlobalLibraryView));
        }

        /// <summary>
        /// Initialization of the module
        /// </summary>
        /// <param name="containerProvider">Container provider to resolve certain types</param>
        public void OnInitialized(IContainerProvider containerProvider)
        {
            _regionManager.RegisterViewWithRegion(RegionNames.ProjectLibraryRegion, typeof(ProjectLibraryView));
            _regionManager.RegisterViewWithRegion(RegionNames.GlobalLibraryRegion, typeof(GlobalLibraryView));
        }

    }
}
