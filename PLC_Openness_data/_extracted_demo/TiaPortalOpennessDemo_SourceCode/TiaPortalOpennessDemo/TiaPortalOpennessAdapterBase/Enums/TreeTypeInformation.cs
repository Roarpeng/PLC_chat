namespace TiaPortalOpennessAdapterBase.Enums
{
    /// <summary>
    /// Tree type information enum to decouple api from application
    /// </summary>
    public enum TreeTypeInformation
    {
        IsOther                   = 0,
        IsTypeGroup               = 1,
        IsFolderGroup             = 2,
        IsType                    = 3,
        IsDevice                  = 4,
        IsMasterCopy              = 5,
        IsTypeVersion             = 6,
        IsDeviceUserGroup         = 11,
        IsDeviceSystemGroup       = 12,
        IsUnpluggedDevice         = 13,
        IsSoftwareUnitGroup       = 14,
        IsSoftwareUnit            = 15,
        IsProgramBlockGroup       = 16,
        IsProgramBlock            = 17,
        IsTechnologicalGroup      = 18,
        IsTechnological           = 19,
        IsExternalSourceGroup     = 20,
        IsExternalSource          = 21,
        IsTagTableGroup           = 22,
        IsTagTable                = 23,
        IsPlcDataTypeGroup        = 24,
        IsPlcDataType             = 25,
        IsPlcSystemTypeGroup      = 26,
        IsPlcSystemType           = 27,
        IsPlcTypeUserGroup        = 28,
        IsPlcUserType             = 29,
        IsWatchAndForceTableGroup = 30,
        IsWatchAndForceTable      = 31,
        IsHmiScreenGroup          = 32,
        IsHmiScreen               = 33,
        IsHmiAlarmGroup           = 34,
        IsHmiAlarm                = 35,
        IsHmiSystemTagGroup       = 36,
        IsHmiSystemTag            = 37,
        IsHmiTagTableGroup        = 38,
        IsHmiTagTable             = 39,
        IsHmiTagGroup             = 40,
        IsHmiTag                  = 41,
        IsSysLib                  = 98,
        IsUserLib                 = 99,
        IsProject                 = 100,
        IsEmpty                   = 1000
    }
}
