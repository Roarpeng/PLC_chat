Imports System
Imports System.Runtime.InteropServices
Imports System.Security
Imports System.Text.RegularExpressions
Imports System.Windows.Forms
Imports Basic_Project_Generator.Models

Namespace UserInterfaces
    Public Class PlcSecuritySettings
#Region "fields"

        Private _confirmMasterSecretPassword As SecureString
        Private _confirmAccessLevelPassword As SecureString
        Private _confirmDisplayProtectionPassword As SecureString
        Private _plcAccessLevel As PlcAccessLevel
        Private _displayAutoLogoff As DisplayAutoLogoff

#End Region

#Region "ctor"

        Public Sub New()
            InitializeComponent()

            btn_Create.DialogResult = DialogResult.OK
            btn_Cancel.DialogResult = DialogResult.Cancel
        End Sub

#End Region

#Region "properties"

        Public Property AccessLevel As String

        Public Property MasterSecretPassword As SecureString

        Public Property AccessLevelPassword As SecureString

        Public Property DisplayProtectionPassword As SecureString

        Public Property IncludeFailsafe As Boolean

        Public Property ProtectPlcConfiguration As Boolean

        Public Property ProtectPlcConfigurationError As Boolean

        Public Property AccessLevelError As Boolean

        Public Shared Property ExceptionOccurred As Boolean

        Public Property DisplayProtection As Boolean

        Public Property DisplayProtectionError As Boolean

        Public Property TimeUntilDisplayAutoLogoff As String

#End Region

#Region "methods"

        ''' <summary>
        ''' Initialization of controls
        ''' </summary>
        ''' <paramname="sender"></param>
        ''' <paramname="e"></param>
        Private Sub PlcSecuritySettings_Load(sender As Object, e As EventArgs) Handles MyBase.Load
            cbo_PlcProtectionConfiguration.Checked = True

            _plcAccessLevel = New PlcAccessLevel(IncludeFailsafe)
            cob_AccessLevel.ValueMember = _plcAccessLevel.GetNamePropertyName()
            cob_AccessLevel.Text = _plcAccessLevel.GetTagPropertyName()

            For Each feAccessLevel In _plcAccessLevel.AccessLevels
                cob_AccessLevel.Items.Add(feAccessLevel)
            Next

            cob_AccessLevel.SelectedIndex = 0

            _displayAutoLogoff = New DisplayAutoLogoff()
            cob_TimeUntilAutoLogoff.ValueMember = _displayAutoLogoff.GetNamePropertyName()
            cob_TimeUntilAutoLogoff.Text = _displayAutoLogoff.GetTagPropertyName()

            cbo_DisplayProtection.Checked = True

            For Each autoLogoff In _displayAutoLogoff.AutoLogoffs
                cob_TimeUntilAutoLogoff.Items.Add(autoLogoff)
            Next

            cob_TimeUntilAutoLogoff.SelectedIndex = 5
        End Sub

        ''' <summary>
        ''' Activate or deactivate the PLC Protection controls
        ''' </summary>
        ''' <paramname="sender"></param>
        ''' <paramname="e"></param>
        Private Sub cbo_PlcProtectionConfiguration_CheckedChanged(sender As Object, e As EventArgs) Handles cbo_PlcProtectionConfiguration.CheckedChanged
            ProtectPlcConfiguration = cbo_PlcProtectionConfiguration.Checked

            txb_MasterSecretPassword.Enabled = cbo_PlcProtectionConfiguration.Checked
            txb_ConfirmMasterSecretPassword.Enabled = cbo_PlcProtectionConfiguration.Checked
        End Sub

        ''' <summary>
        ''' Check input when leave the control
        ''' </summary>
        ''' <paramname="sender"></param>
        ''' <paramname="e"></param>
        Private Sub txb_MasterSecretPassword_Leave(sender As Object, e As EventArgs) Handles txb_MasterSecretPassword.Leave
            If Not String.IsNullOrEmpty(txb_MasterSecretPassword.Text) Then
                If Not CheckPasswordRule(txb_MasterSecretPassword.Text, False) Then
                    ProtectPlcConfigurationError = True
                End If
            End If
        End Sub

        ''' <summary>
        ''' Check input when leave the control
        ''' </summary>
        ''' <paramname="sender"></param>
        ''' <paramname="e"></param>
        Private Sub txb_ConfirmPlcProtectionPassword_Leave(sender As Object, e As EventArgs) Handles txb_ConfirmMasterSecretPassword.Leave
            If Not String.IsNullOrEmpty(txb_ConfirmMasterSecretPassword.Text) Then
                If Not CheckPasswordRule(txb_ConfirmMasterSecretPassword.Text, False) Then
                    ProtectPlcConfigurationError = True
                Else
                    MasterSecretPassword = GetSecureString(txb_MasterSecretPassword.Text)
                    _confirmMasterSecretPassword = GetSecureString(txb_ConfirmMasterSecretPassword.Text)

                    ProtectPlcConfigurationError = SecureStringEqual("PLC Protection password", MasterSecretPassword, _confirmMasterSecretPassword)
                End If
            End If
        End Sub

        ''' <summary>
        ''' Activate or deactivate the access level protection controls
        ''' </summary>
        ''' <paramname="sender"></param>
        ''' <paramname="e"></param>
        Private Sub cob_AccessLevel_SelectedIndexChanged(sender As Object, e As EventArgs) Handles cob_AccessLevel.SelectedIndexChanged
            AccessLevel = CType(cob_AccessLevel.SelectedItem, AccessLevel).Tag

            If cob_AccessLevel.Items.Count = 4 AndAlso cob_AccessLevel.SelectedIndex = 0 OrElse cob_AccessLevel.Items.Count = 5 AndAlso (cob_AccessLevel.SelectedIndex = 0 OrElse cob_AccessLevel.SelectedIndex = 1) Then
                txb_AccessLevelPassword.Enabled = False
                txb_ConfirmAccessLevelPassword.Enabled = False
            Else
                txb_AccessLevelPassword.Enabled = True
                txb_ConfirmAccessLevelPassword.Enabled = True
            End If
        End Sub

        ''' <summary>
        ''' Check input when leave the control
        ''' </summary>
        ''' <paramname="sender"></param>
        ''' <paramname="e"></param>
        Private Sub txb_AccessLevelPassword_Leave(sender As Object, e As EventArgs) Handles txb_AccessLevelPassword.Leave
            If Not String.IsNullOrEmpty(txb_AccessLevelPassword.Text) Then
                If Not CheckPasswordRule(txb_AccessLevelPassword.Text, False) Then
                    AccessLevelError = True
                End If
            End If
        End Sub

        ''' <summary>
        ''' Check input when leave the control
        ''' </summary>
        ''' <paramname="sender"></param>
        ''' <paramname="e"></param>
        Private Sub txb_ConfirmAccessLevelPassword_Leave(sender As Object, e As EventArgs) Handles txb_ConfirmAccessLevelPassword.Leave
            If Not String.IsNullOrEmpty(txb_ConfirmAccessLevelPassword.Text) Then
                If Not CheckPasswordRule(txb_ConfirmAccessLevelPassword.Text, False) Then
                    AccessLevelError = True
                Else
                    AccessLevelPassword = GetSecureString(txb_AccessLevelPassword.Text)
                    _confirmAccessLevelPassword = GetSecureString(txb_ConfirmAccessLevelPassword.Text)

                    AccessLevelError = SecureStringEqual("Access Level password", AccessLevelPassword, _confirmAccessLevelPassword)
                End If
            End If
        End Sub

        ''' <summary>
        ''' Activate or deactivate the display protection and the controls
        ''' </summary>
        ''' <paramname="sender"></param>
        ''' <paramname="e"></param>
        Private Sub cbo_DisplayProtection_CheckedChanged(sender As Object, e As EventArgs) Handles cbo_DisplayProtection.CheckedChanged
            DisplayProtection = cbo_DisplayProtection.Checked

            txb_DisplayProtectionPassword.Enabled = cbo_DisplayProtection.Checked
            txb_ConfirmDisplayProtectionPassword.Enabled = cbo_DisplayProtection.Checked
            cob_TimeUntilAutoLogoff.Enabled = cbo_DisplayProtection.Checked
        End Sub

        ''' <summary>
        ''' Check input when leave the control
        ''' </summary>
        ''' <paramname="sender"></param>
        ''' <paramname="e"></param>
        Private Sub txb_DisplayProtectionPassword_Leave(sender As Object, e As EventArgs) Handles txb_DisplayProtectionPassword.Leave
            If Not String.IsNullOrEmpty(txb_DisplayProtectionPassword.Text) Then
                If Not CheckPasswordRule(txb_DisplayProtectionPassword.Text.ToUpper(), True) Then
                    DisplayProtectionError = True
                End If
            End If
        End Sub

        ''' <summary>
        ''' Check input when leave the control
        ''' </summary>
        ''' <paramname="sender"></param>
        ''' <paramname="e"></param>
        Private Sub txb_ConfirmDisplayProtectionPassword_Leave(sender As Object, e As EventArgs) Handles txb_ConfirmDisplayProtectionPassword.Leave
            If Not String.IsNullOrEmpty(txb_ConfirmDisplayProtectionPassword.Text) Then
                If Not CheckPasswordRule(txb_ConfirmDisplayProtectionPassword.Text.ToUpper(), True) Then
                    ProtectPlcConfigurationError = True
                Else
                    DisplayProtectionPassword = GetSecureString(txb_DisplayProtectionPassword.Text.ToUpper())
                    _confirmDisplayProtectionPassword = GetSecureString(txb_ConfirmDisplayProtectionPassword.Text.ToUpper())

                    DisplayProtectionError = SecureStringEqual("Display Protection password", DisplayProtectionPassword, _confirmDisplayProtectionPassword)
                End If
            End If
        End Sub

        ''' <summary>
        ''' Set the selected time for display auto logoff
        ''' </summary>
        ''' <paramname="sender"></param>
        ''' <paramname="e"></param>
        Private Sub cob_TimeUntilAutoLogoff_SelectedIndexChanged(sender As Object, e As EventArgs) Handles cob_TimeUntilAutoLogoff.SelectedIndexChanged
            TimeUntilDisplayAutoLogoff = CType(cob_TimeUntilAutoLogoff.SelectedItem, AutoLogoff).Tag
        End Sub

        ''' <summary>
        ''' Validation the input
        ''' </summary>
        Private Sub ValidationProvider()
            ExceptionOccurred = False
            ProtectPlcConfigurationError = False
            AccessLevelError = False

            If cbo_PlcProtectionConfiguration.Checked Then
                ProtectPlcConfigurationError = SecureStringEqual("PLC Protection password", MasterSecretPassword, _confirmMasterSecretPassword)
            End If

            If cob_AccessLevel.Items.Count = 4 AndAlso cob_AccessLevel.SelectedIndex > 0 Then
                AccessLevelError = SecureStringEqual("Access Level password", AccessLevelPassword, _confirmAccessLevelPassword)
            End If

            If cob_AccessLevel.Items.Count = 5 AndAlso cob_AccessLevel.SelectedIndex > 1 Then
                AccessLevelError = SecureStringEqual("Access Level password", AccessLevelPassword, _confirmAccessLevelPassword)
            End If
        End Sub

        ''' <summary>
        ''' Validation the input and canceling close if an error occurred
        ''' </summary>
        ''' <paramname="sender"></param>
        ''' <paramname="e"></param>
        Private Sub PlcSecuritySettings_FormClosing(sender As Object, e As FormClosingEventArgs) Handles MyBase.FormClosing
            If DialogResult = DialogResult.OK Then
                ValidationProvider()

                If ProtectPlcConfigurationError OrElse AccessLevelError OrElse ExceptionOccurred Then
                    e.Cancel = True
                End If
            End If
        End Sub

        ''' <summary>
        ''' Check the password string
        ''' </summary>
        ''' <paramname="password"></param>
        ''' <paramname="cpuDisplay"></param>
        ''' <returns></returns>
        Private Shared Function CheckPasswordRule(password As String, cpuDisplay As Boolean) As Boolean
            Dim match As Match

            Dim plcRegex = New Regex("^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{9,}$")
            Dim cpuRegex = New Regex("^(?=.*[A-Z])(?=.*\d)[A-Z\d]{3,8}$")

            If cpuDisplay Then
                match = cpuRegex.Match(password)
            Else
                match = plcRegex.Match(password)
            End If

            If Not match.Success Then
                If cpuDisplay Then
                    MessageBox.Show("The password must contain 3-8 characters. Only upper case letters and numbers are allowed. Lower case letters will be entered automatically as upper case letters.!", "Exception", MessageBoxButtons.OK, MessageBoxIcon.Information)
                Else
                    MessageBox.Show("The password must be at least 9 characters long and contain a capital letter, a number and a special character (@$!%*?&)!", "Exception", MessageBoxButtons.OK, MessageBoxIcon.Information)
                End If
            End If

            Return match.Success
        End Function

        ''' <summary>
        ''' Create a secure string from input
        ''' </summary>
        ''' <paramname="plainString"></param>
        ''' <returns></returns>
        Private Shared Function GetSecureString(plainString As String) As SecureString
            Dim secureString As SecureString = Nothing

            Try
                If Not Equals(plainString, Nothing) Then
                    secureString = New SecureString()

                    For Each c In plainString
                        secureString.AppendChar(c)
                    Next

                    secureString.MakeReadOnly()
                End If
            Catch exception As Exception
                ExceptionOccurred = True
                MessageBox.Show(exception.Message, "Exception", MessageBoxButtons.OK, MessageBoxIcon.Error)
            End Try

            Return secureString
        End Function

        ''' <summary>
        ''' Compare the password and the confirmation
        ''' </summary>
        ''' <paramname="passwordName"></param>
        ''' <paramname="password"></param>
        ''' <paramname="confirmPassword"></param>
        ''' <returns></returns>
        Private Shared Function SecureStringEqual(passwordName As String, password As SecureString, confirmPassword As SecureString) As Boolean
            Dim errorOccurred = False

            If password Is Nothing OrElse confirmPassword Is Nothing Then
                MessageBox.Show("The " & passwordName & " and confirm password must not be null!", "Exception", MessageBoxButtons.OK, MessageBoxIcon.Error)
                Return True
            End If

            If password.Length <> confirmPassword.Length Then
                MessageBox.Show("The " & passwordName & " and confirm password do not match!", "Exception", MessageBoxButtons.OK, MessageBoxIcon.Error)
                Return True
            End If

            Dim secureStringPasswordPtr = IntPtr.Zero
            Dim secureStringConfirmPasswordPtr = IntPtr.Zero

            Try
                secureStringPasswordPtr = Marshal.SecureStringToBSTR(password)
                secureStringConfirmPasswordPtr = Marshal.SecureStringToBSTR(confirmPassword)

                Dim stringPassword = Marshal.PtrToStringBSTR(secureStringPasswordPtr)
                Dim stringConfirmPassword = Marshal.PtrToStringBSTR(secureStringConfirmPasswordPtr)

                If Not stringPassword.Equals(stringConfirmPassword) Then
                    errorOccurred = True
                    MessageBox.Show("The " & passwordName & " and confirm password do not match!", "Exception", MessageBoxButtons.OK, MessageBoxIcon.Error)
                End If
            Catch exception As Exception
                ExceptionOccurred = True
                MessageBox.Show(exception.Message, "Exception", MessageBoxButtons.OK, MessageBoxIcon.Error)
            Finally
                If secureStringPasswordPtr <> IntPtr.Zero Then
                    Marshal.ZeroFreeBSTR(secureStringPasswordPtr)
                End If

                If secureStringConfirmPasswordPtr <> IntPtr.Zero Then
                    Marshal.ZeroFreeBSTR(secureStringConfirmPasswordPtr)
                End If
            End Try

            Return errorOccurred
        End Function

#End Region
    End Class
End Namespace
