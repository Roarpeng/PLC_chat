Namespace UserInterfaces
    Partial Class PlcSecuritySettings
        Inherits System.Windows.Forms.Form
        ''' <summary>
        ''' Required designer variable.
        ''' </summary>
        Private components As System.ComponentModel.IContainer = Nothing

        ''' <summary>
        ''' Clean up any resources being used.
        ''' </summary>
        ''' <paramname="disposing">true if managed resources should be disposed; otherwise, false.</param>
        Protected Overrides Sub Dispose(ByVal disposing As Boolean)
            If disposing AndAlso components IsNot Nothing Then
                components.Dispose()
            End If

            MyBase.Dispose(disposing)
        End Sub

#Region "Windows Form Designer generated code"

        ''' <summary>
        ''' Required method for Designer support - do not modify
        ''' the contents of this method with the code editor.
        ''' </summary>
        Private Sub InitializeComponent()
        Me.btn_Create = New System.Windows.Forms.Button()
        Me.btn_Cancel = New System.Windows.Forms.Button()
        Me.grb_PlcProtectionConfiguration = New System.Windows.Forms.GroupBox()
        Me.cbo_PlcProtectionConfiguration = New System.Windows.Forms.CheckBox()
        Me.txb_ConfirmMasterSecretPassword = New System.Windows.Forms.TextBox()
        Me.txb_MasterSecretPassword = New System.Windows.Forms.TextBox()
        Me.lab_ConfirmPlcProtectinPassword = New System.Windows.Forms.Label()
        Me.lab_NewPlcProtectionPassword = New System.Windows.Forms.Label()
        Me.grb_PlzAccessProtection = New System.Windows.Forms.GroupBox()
        Me.txb_ConfirmAccessLevelPassword = New System.Windows.Forms.TextBox()
        Me.txb_AccessLevelPassword = New System.Windows.Forms.TextBox()
        Me.lab_ConfirmAccessLevelPassword = New System.Windows.Forms.Label()
        Me.lab_NewAccessLevelPassword = New System.Windows.Forms.Label()
        Me.lab_AccessLevel = New System.Windows.Forms.Label()
        Me.cob_AccessLevel = New System.Windows.Forms.ComboBox()
        Me.grb_DisplayProtection = New System.Windows.Forms.GroupBox()
        Me.cob_TimeUntilAutoLogoff = New System.Windows.Forms.ComboBox()
        Me.lab_TimeUntilAutoLogoff = New System.Windows.Forms.Label()
        Me.txb_ConfirmDisplayProtectionPassword = New System.Windows.Forms.TextBox()
        Me.txb_DisplayProtectionPassword = New System.Windows.Forms.TextBox()
        Me.lab_ConfirmDisplayProtectinPassword = New System.Windows.Forms.Label()
        Me.lab_NewDisplayProtectionPassword = New System.Windows.Forms.Label()
        Me.cbo_DisplayProtection = New System.Windows.Forms.CheckBox()
        Me.grb_PlcProtectionConfiguration.SuspendLayout
        Me.grb_PlzAccessProtection.SuspendLayout
        Me.grb_DisplayProtection.SuspendLayout
        Me.SuspendLayout
        '
        'btn_Create
        '
        Me.btn_Create.Location = New System.Drawing.Point(139, 394)
        Me.btn_Create.Name = "btn_Create"
        Me.btn_Create.Size = New System.Drawing.Size(99, 23)
        Me.btn_Create.TabIndex = 3
        Me.btn_Create.Text = "Create"
        Me.btn_Create.UseVisualStyleBackColor = true
        '
        'btn_Cancel
        '
        Me.btn_Cancel.Location = New System.Drawing.Point(244, 394)
        Me.btn_Cancel.Name = "btn_Cancel"
        Me.btn_Cancel.Size = New System.Drawing.Size(99, 23)
        Me.btn_Cancel.TabIndex = 4
        Me.btn_Cancel.Text = "Cancel"
        Me.btn_Cancel.UseVisualStyleBackColor = true
        '
        'grb_PlcProtectionConfiguration
        '
        Me.grb_PlcProtectionConfiguration.Controls.Add(Me.cbo_PlcProtectionConfiguration)
        Me.grb_PlcProtectionConfiguration.Controls.Add(Me.txb_ConfirmMasterSecretPassword)
        Me.grb_PlcProtectionConfiguration.Controls.Add(Me.txb_MasterSecretPassword)
        Me.grb_PlcProtectionConfiguration.Controls.Add(Me.lab_ConfirmPlcProtectinPassword)
        Me.grb_PlcProtectionConfiguration.Controls.Add(Me.lab_NewPlcProtectionPassword)
        Me.grb_PlcProtectionConfiguration.Location = New System.Drawing.Point(12, 12)
        Me.grb_PlcProtectionConfiguration.Name = "grb_PlcProtectionConfiguration"
        Me.grb_PlcProtectionConfiguration.Size = New System.Drawing.Size(331, 113)
        Me.grb_PlcProtectionConfiguration.TabIndex = 0
        Me.grb_PlcProtectionConfiguration.TabStop = false
        Me.grb_PlcProtectionConfiguration.Text = "Protection of confidential PLC data"
        '
        'cbo_PlcProtectionConfiguration
        '
        Me.cbo_PlcProtectionConfiguration.AutoSize = true
        Me.cbo_PlcProtectionConfiguration.Location = New System.Drawing.Point(128, 25)
        Me.cbo_PlcProtectionConfiguration.Name = "cbo_PlcProtectionConfiguration"
        Me.cbo_PlcProtectionConfiguration.Size = New System.Drawing.Size(189, 17)
        Me.cbo_PlcProtectionConfiguration.TabIndex = 0
        Me.cbo_PlcProtectionConfiguration.Text = "Protect the PLC configuration data"
        Me.cbo_PlcProtectionConfiguration.UseVisualStyleBackColor = true
        '
        'txb_ConfirmMasterSecretPassword
        '
        Me.txb_ConfirmMasterSecretPassword.Location = New System.Drawing.Point(128, 74)
        Me.txb_ConfirmMasterSecretPassword.Name = "txb_ConfirmMasterSecretPassword"
        Me.txb_ConfirmMasterSecretPassword.PasswordChar = Global.Microsoft.VisualBasic.ChrW(42)
        Me.txb_ConfirmMasterSecretPassword.Size = New System.Drawing.Size(191, 20)
        Me.txb_ConfirmMasterSecretPassword.TabIndex = 4
        '
        'txb_MasterSecretPassword
        '
        Me.txb_MasterSecretPassword.Location = New System.Drawing.Point(128, 48)
        Me.txb_MasterSecretPassword.Name = "txb_MasterSecretPassword"
        Me.txb_MasterSecretPassword.PasswordChar = Global.Microsoft.VisualBasic.ChrW(42)
        Me.txb_MasterSecretPassword.Size = New System.Drawing.Size(191, 20)
        Me.txb_MasterSecretPassword.TabIndex = 2
        '
        'lab_ConfirmPlcProtectinPassword
        '
        Me.lab_ConfirmPlcProtectinPassword.AutoSize = true
        Me.lab_ConfirmPlcProtectinPassword.Location = New System.Drawing.Point(32, 77)
        Me.lab_ConfirmPlcProtectinPassword.Name = "lab_ConfirmPlcProtectinPassword"
        Me.lab_ConfirmPlcProtectinPassword.Size = New System.Drawing.Size(90, 13)
        Me.lab_ConfirmPlcProtectinPassword.TabIndex = 3
        Me.lab_ConfirmPlcProtectinPassword.Text = "Confirm password"
        '
        'lab_NewPlcProtectionPassword
        '
        Me.lab_NewPlcProtectionPassword.AutoSize = true
        Me.lab_NewPlcProtectionPassword.Location = New System.Drawing.Point(45, 51)
        Me.lab_NewPlcProtectionPassword.Name = "lab_NewPlcProtectionPassword"
        Me.lab_NewPlcProtectionPassword.Size = New System.Drawing.Size(77, 13)
        Me.lab_NewPlcProtectionPassword.TabIndex = 1
        Me.lab_NewPlcProtectionPassword.Text = "New password"
        '
        'grb_PlzAccessProtection
        '
        Me.grb_PlzAccessProtection.Controls.Add(Me.txb_ConfirmAccessLevelPassword)
        Me.grb_PlzAccessProtection.Controls.Add(Me.txb_AccessLevelPassword)
        Me.grb_PlzAccessProtection.Controls.Add(Me.lab_ConfirmAccessLevelPassword)
        Me.grb_PlzAccessProtection.Controls.Add(Me.lab_NewAccessLevelPassword)
        Me.grb_PlzAccessProtection.Controls.Add(Me.lab_AccessLevel)
        Me.grb_PlzAccessProtection.Controls.Add(Me.cob_AccessLevel)
        Me.grb_PlzAccessProtection.Location = New System.Drawing.Point(12, 131)
        Me.grb_PlzAccessProtection.Name = "grb_PlzAccessProtection"
        Me.grb_PlzAccessProtection.Size = New System.Drawing.Size(331, 119)
        Me.grb_PlzAccessProtection.TabIndex = 1
        Me.grb_PlzAccessProtection.TabStop = false
        Me.grb_PlzAccessProtection.Text = "PLC access protection"
        '
        'txb_ConfirmAccessLevelPassword
        '
        Me.txb_ConfirmAccessLevelPassword.Location = New System.Drawing.Point(128, 79)
        Me.txb_ConfirmAccessLevelPassword.Name = "txb_ConfirmAccessLevelPassword"
        Me.txb_ConfirmAccessLevelPassword.PasswordChar = Global.Microsoft.VisualBasic.ChrW(42)
        Me.txb_ConfirmAccessLevelPassword.Size = New System.Drawing.Size(191, 20)
        Me.txb_ConfirmAccessLevelPassword.TabIndex = 5
        '
        'txb_AccessLevelPassword
        '
        Me.txb_AccessLevelPassword.Location = New System.Drawing.Point(128, 53)
        Me.txb_AccessLevelPassword.Name = "txb_AccessLevelPassword"
        Me.txb_AccessLevelPassword.PasswordChar = Global.Microsoft.VisualBasic.ChrW(42)
        Me.txb_AccessLevelPassword.Size = New System.Drawing.Size(191, 20)
        Me.txb_AccessLevelPassword.TabIndex = 3
        '
        'lab_ConfirmAccessLevelPassword
        '
        Me.lab_ConfirmAccessLevelPassword.AutoSize = true
        Me.lab_ConfirmAccessLevelPassword.Location = New System.Drawing.Point(32, 82)
        Me.lab_ConfirmAccessLevelPassword.Name = "lab_ConfirmAccessLevelPassword"
        Me.lab_ConfirmAccessLevelPassword.Size = New System.Drawing.Size(90, 13)
        Me.lab_ConfirmAccessLevelPassword.TabIndex = 4
        Me.lab_ConfirmAccessLevelPassword.Text = "Confirm password"
        '
        'lab_NewAccessLevelPassword
        '
        Me.lab_NewAccessLevelPassword.AutoSize = true
        Me.lab_NewAccessLevelPassword.Location = New System.Drawing.Point(45, 56)
        Me.lab_NewAccessLevelPassword.Name = "lab_NewAccessLevelPassword"
        Me.lab_NewAccessLevelPassword.Size = New System.Drawing.Size(77, 13)
        Me.lab_NewAccessLevelPassword.TabIndex = 2
        Me.lab_NewAccessLevelPassword.Text = "New password"
        '
        'lab_AccessLevel
        '
        Me.lab_AccessLevel.AutoSize = true
        Me.lab_AccessLevel.Location = New System.Drawing.Point(55, 29)
        Me.lab_AccessLevel.Name = "lab_AccessLevel"
        Me.lab_AccessLevel.Size = New System.Drawing.Size(67, 13)
        Me.lab_AccessLevel.TabIndex = 0
        Me.lab_AccessLevel.Text = "Access level"
        '
        'cob_AccessLevel
        '
        Me.cob_AccessLevel.DropDownStyle = System.Windows.Forms.ComboBoxStyle.DropDownList
        Me.cob_AccessLevel.FormattingEnabled = true
        Me.cob_AccessLevel.Location = New System.Drawing.Point(128, 26)
        Me.cob_AccessLevel.Name = "cob_AccessLevel"
        Me.cob_AccessLevel.Size = New System.Drawing.Size(191, 21)
        Me.cob_AccessLevel.TabIndex = 1
        '
        'grb_DisplayProtection
        '
        Me.grb_DisplayProtection.Controls.Add(Me.cob_TimeUntilAutoLogoff)
        Me.grb_DisplayProtection.Controls.Add(Me.lab_TimeUntilAutoLogoff)
        Me.grb_DisplayProtection.Controls.Add(Me.txb_ConfirmDisplayProtectionPassword)
        Me.grb_DisplayProtection.Controls.Add(Me.txb_DisplayProtectionPassword)
        Me.grb_DisplayProtection.Controls.Add(Me.lab_ConfirmDisplayProtectinPassword)
        Me.grb_DisplayProtection.Controls.Add(Me.lab_NewDisplayProtectionPassword)
        Me.grb_DisplayProtection.Controls.Add(Me.cbo_DisplayProtection)
        Me.grb_DisplayProtection.Location = New System.Drawing.Point(12, 256)
        Me.grb_DisplayProtection.Name = "grb_DisplayProtection"
        Me.grb_DisplayProtection.Size = New System.Drawing.Size(331, 132)
        Me.grb_DisplayProtection.TabIndex = 2
        Me.grb_DisplayProtection.TabStop = false
        Me.grb_DisplayProtection.Text = "CPU display protection"
        '
        'cob_TimeUntilAutoLogoff
        '
        Me.cob_TimeUntilAutoLogoff.DropDownStyle = System.Windows.Forms.ComboBoxStyle.DropDownList
        Me.cob_TimeUntilAutoLogoff.FormattingEnabled = true
        Me.cob_TimeUntilAutoLogoff.Location = New System.Drawing.Point(128, 100)
        Me.cob_TimeUntilAutoLogoff.Name = "cob_TimeUntilAutoLogoff"
        Me.cob_TimeUntilAutoLogoff.Size = New System.Drawing.Size(191, 21)
        Me.cob_TimeUntilAutoLogoff.TabIndex = 6
        '
        'lab_TimeUntilAutoLogoff
        '
        Me.lab_TimeUntilAutoLogoff.AutoSize = true
        Me.lab_TimeUntilAutoLogoff.Location = New System.Drawing.Point(17, 103)
        Me.lab_TimeUntilAutoLogoff.Name = "lab_TimeUntilAutoLogoff"
        Me.lab_TimeUntilAutoLogoff.Size = New System.Drawing.Size(105, 13)
        Me.lab_TimeUntilAutoLogoff.TabIndex = 5
        Me.lab_TimeUntilAutoLogoff.Text = "Time until auto logoff"
        '
        'txb_ConfirmDisplayProtectionPassword
        '
        Me.txb_ConfirmDisplayProtectionPassword.Location = New System.Drawing.Point(128, 74)
        Me.txb_ConfirmDisplayProtectionPassword.Name = "txb_ConfirmDisplayProtectionPassword"
        Me.txb_ConfirmDisplayProtectionPassword.PasswordChar = Global.Microsoft.VisualBasic.ChrW(42)
        Me.txb_ConfirmDisplayProtectionPassword.Size = New System.Drawing.Size(191, 20)
        Me.txb_ConfirmDisplayProtectionPassword.TabIndex = 4
        '
        'txb_DisplayProtectionPassword
        '
        Me.txb_DisplayProtectionPassword.Location = New System.Drawing.Point(128, 48)
        Me.txb_DisplayProtectionPassword.Name = "txb_DisplayProtectionPassword"
        Me.txb_DisplayProtectionPassword.PasswordChar = Global.Microsoft.VisualBasic.ChrW(42)
        Me.txb_DisplayProtectionPassword.Size = New System.Drawing.Size(191, 20)
        Me.txb_DisplayProtectionPassword.TabIndex = 2
        '
        'lab_ConfirmDisplayProtectinPassword
        '
        Me.lab_ConfirmDisplayProtectinPassword.AutoSize = true
        Me.lab_ConfirmDisplayProtectinPassword.Location = New System.Drawing.Point(32, 77)
        Me.lab_ConfirmDisplayProtectinPassword.Name = "lab_ConfirmDisplayProtectinPassword"
        Me.lab_ConfirmDisplayProtectinPassword.Size = New System.Drawing.Size(90, 13)
        Me.lab_ConfirmDisplayProtectinPassword.TabIndex = 3
        Me.lab_ConfirmDisplayProtectinPassword.Text = "Confirm password"
        '
        'lab_NewDisplayProtectionPassword
        '
        Me.lab_NewDisplayProtectionPassword.AutoSize = true
        Me.lab_NewDisplayProtectionPassword.Location = New System.Drawing.Point(45, 51)
        Me.lab_NewDisplayProtectionPassword.Name = "lab_NewDisplayProtectionPassword"
        Me.lab_NewDisplayProtectionPassword.Size = New System.Drawing.Size(77, 13)
        Me.lab_NewDisplayProtectionPassword.TabIndex = 1
        Me.lab_NewDisplayProtectionPassword.Text = "New password"
        '
        'cbo_DisplayProtection
        '
        Me.cbo_DisplayProtection.AutoSize = true
        Me.cbo_DisplayProtection.Location = New System.Drawing.Point(128, 25)
        Me.cbo_DisplayProtection.Name = "cbo_DisplayProtection"
        Me.cbo_DisplayProtection.Size = New System.Drawing.Size(144, 17)
        Me.cbo_DisplayProtection.TabIndex = 0
        Me.cbo_DisplayProtection.Text = "Enable display protection"
        Me.cbo_DisplayProtection.UseVisualStyleBackColor = true
        '
        'PlcSecuritySettings
        '
        Me.AutoScaleDimensions = New System.Drawing.SizeF(6!, 13!)
        Me.AutoScaleMode = System.Windows.Forms.AutoScaleMode.Font
        Me.ClientSize = New System.Drawing.Size(355, 427)
        Me.ControlBox = false
        Me.Controls.Add(Me.grb_DisplayProtection)
        Me.Controls.Add(Me.grb_PlzAccessProtection)
        Me.Controls.Add(Me.grb_PlcProtectionConfiguration)
        Me.Controls.Add(Me.btn_Cancel)
        Me.Controls.Add(Me.btn_Create)
        Me.FormBorderStyle = System.Windows.Forms.FormBorderStyle.FixedDialog
        Me.MaximizeBox = false
        Me.MinimizeBox = false
        Me.Name = "PlcSecuritySettings"
        Me.ShowInTaskbar = false
        Me.StartPosition = System.Windows.Forms.FormStartPosition.CenterParent
        Me.Text = "PLC security settings"
        Me.grb_PlcProtectionConfiguration.ResumeLayout(false)
        Me.grb_PlcProtectionConfiguration.PerformLayout
        Me.grb_PlzAccessProtection.ResumeLayout(false)
        Me.grb_PlzAccessProtection.PerformLayout
        Me.grb_DisplayProtection.ResumeLayout(false)
        Me.grb_DisplayProtection.PerformLayout
        Me.ResumeLayout(false)

End Sub

#End Region

        Private WithEvents btn_Create As System.Windows.Forms.Button
        Private WithEvents btn_Cancel As System.Windows.Forms.Button
        Private WithEvents grb_PlcProtectionConfiguration As System.Windows.Forms.GroupBox
        Private WithEvents lab_ConfirmPlcProtectinPassword As System.Windows.Forms.Label
        Private WithEvents lab_NewPlcProtectionPassword As System.Windows.Forms.Label
        Private WithEvents grb_PlzAccessProtection As System.Windows.Forms.GroupBox
        Private WithEvents cbo_PlcProtectionConfiguration As System.Windows.Forms.CheckBox
        Private WithEvents txb_ConfirmMasterSecretPassword As System.Windows.Forms.TextBox
        Private WithEvents txb_MasterSecretPassword As System.Windows.Forms.TextBox
        Private WithEvents txb_ConfirmAccessLevelPassword As System.Windows.Forms.TextBox
        Private WithEvents txb_AccessLevelPassword As System.Windows.Forms.TextBox
        Private WithEvents lab_ConfirmAccessLevelPassword As System.Windows.Forms.Label
        Private WithEvents lab_NewAccessLevelPassword As System.Windows.Forms.Label
        Private WithEvents lab_AccessLevel As System.Windows.Forms.Label
        Private WithEvents cob_AccessLevel As System.Windows.Forms.ComboBox
        Private WithEvents grb_DisplayProtection As System.Windows.Forms.GroupBox
        Private WithEvents cob_TimeUntilAutoLogoff As System.Windows.Forms.ComboBox
        Private WithEvents lab_TimeUntilAutoLogoff As System.Windows.Forms.Label
        Private WithEvents txb_ConfirmDisplayProtectionPassword As System.Windows.Forms.TextBox
        Private WithEvents txb_DisplayProtectionPassword As System.Windows.Forms.TextBox
        Private WithEvents lab_ConfirmDisplayProtectinPassword As System.Windows.Forms.Label
        Private WithEvents lab_NewDisplayProtectionPassword As System.Windows.Forms.Label
        Private WithEvents cbo_DisplayProtection As System.Windows.Forms.CheckBox
    End Class
End Namespace
