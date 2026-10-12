Imports System.Collections.Generic

Namespace Models
    Public Class PlcAccessLevel
#Region "ctor"

        ' level 0 == PlcProtectionAccessLevel.None;    
        ' level 1 == PlcProtectionAccessLevel.FullAccess;
        ' level 2 == PlcProtectionAccessLevel.ReadAccess;
        ' level 3 == PlcProtectionAccessLevel.HMIAccess;
        ' level 4 == PlcProtectionAccessLevel.NoAccess;
        ' level 5 == PlcProtectionAccessLevel.FullAccessIncludingFailsafe;
        Public Sub New(includeFailsafe As Boolean)
            AccessLevels = New List(Of AccessLevel) From {
                New AccessLevel With {
                    .Name = "Full access (no protection)",
                    .Tag = "FullAccess"
                }
            }

            If includeFailsafe Then
                AccessLevels.Add(New AccessLevel With {
                    .Name = "Full access incl. fail-safe (no protection)",
                    .Tag = "FullAccessIncludingFailsafe"
                })
            End If

            AccessLevels.Add(New AccessLevel With {
                .Name = "Read access",
                .Tag = "ReadAccess"
            })
            AccessLevels.Add(New AccessLevel With {
                .Name = "HMI access",
                .Tag = "HMIAccess"
            })
            AccessLevels.Add(New AccessLevel With {
                .Name = "No access (complete protection)",
                .Tag = "NoAccess"
            })
        End Sub

#End Region

#Region "properties"

        Public Property AccessLevels As List(Of AccessLevel)

#End Region

#Region "methods"

        Public Function GetNamePropertyName() As String
            Return NameOf(AccessLevel.Name)
        End Function

        Public Function GetTagPropertyName() As String
            Return NameOf(AccessLevel.Tag)
        End Function

#End Region
    End Class
End Namespace
